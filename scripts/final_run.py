"""The final `ask` run: N dev hospitals, one model preset, several `hfal ask` processes at once, every answer checked.

    uv run python scripts/final_run.py                      # plan, prompt sizes and cost estimate; asks before spending
    uv run python scripts/final_run.py --yes                # same, without the question
    uv run python scripts/final_run.py --resume RUN_ID      # carry on a stopped run (answers received come from the cache)
    uv run python scripts/final_run.py --check-only RUN_ID  # check a run's files again; no model call

Defaults: Kimi K3 at max effort (`kimi-k3-max`, the model of the 15-hospital v7 pilot; K3.1 paraphrased its quotes, so
most failed verification), prompt v7, 40 dev hospitals drawn at random (seed 20261112)
from the dev hospitals that were NOT in the pilot (data/review/pilot_ids*.txt: the pilot review tunes on those),
2 processes. Eval hospitals are asked only from a list with `--hospitals-file PATH --set eval`.

What it does:
  1. Checks: settings.yaml's prompt_version is the one asked for and agrees with criteria_file; each prompt is built
     without calling the model (too large for one call = recorded and not asked, never truncated); prints the cost
     estimate and asks before spending.
  2. Runs `uv run hfal ask --model PRESET --run-id RUN_ID --hospital ...` in WORKERS processes, the hospitals dealt
     out by prompt size so the processes finish together. Logs: runs/RUN_ID/logs/. Every 30 s it reads the usage
     ledger and stops all processes if the run has spent more than --budget-usd.
  3. Checks every hospital's file (runcheck.py): right hospital, run, model, effort and prompt version, an allowed
     answer for each criterion exactly once, the reported lists, the consistency check. Hospitals with a problem are
     asked again in one process, up to --retry-rounds times, and only while each round fixes something (a failed
     call is billed, so it does not keep paying for a hospital that keeps failing).
  4. Rewrites runs/RUN_ID/failed.json, skipped.json and usage.json for the whole run (the processes overwrite each
     other's), writes final_run.json (the plan) and final_check.json (the result of the check).
  5. Only when every hospital is recorded properly: `hfal grade`, `hfal score`, `hfal size-check`, `hfal report`,
     `hfal usage`. No judge. The report goes to its own folder, results/DATE_PRESET_VERSION/ (refuses to overwrite
     one); results/latest/ is NOT touched, so the report a dashboard reads stays as it was.

Hospital ids are written only under runs/ (git-ignored); the terminal shows ids only for hospitals with a problem.
"""

import argparse
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from hfal import paths, runcheck
from hfal.cli import check_versions, working_set
from hfal.files import read_json
from hfal.model import model_id, provider

PILOT_FILES = ["pilot_ids.txt", "pilot_ids_partly.txt"]
MAX_CALL_USD = 1.50             # the most one Kimi K3-at-max hospital cost in the pilot was $1.33 (ledger, Nov 12)
EST_OUTPUT_TOKENS = 28_000      # Kimi K3 at max averaged 28,242 output tokens over 14 hospitals (ledger, Nov 12)
CHARS_PER_TOKEN = 2.3           # measured on real prompts (PLAN.md); `ask --dry-run` divides by 4, too low


def pilot_ids() -> set[str]:
    """The pilot hospitals, which the final run must never ask (their answers stay as the pilot left them).
    pilot_ids.txt must exist and list them: without it the draw could pick pilot hospitals, so the script stops."""
    main = paths.DATA / "review" / PILOT_FILES[0]
    if not main.exists():
        raise SystemExit(f"{main} not found: it lists the pilot hospitals the final run must leave alone")
    pilot = set()
    for name in PILOT_FILES:
        f = paths.DATA / "review" / name
        if f.exists():
            pilot |= {line.strip() for line in f.read_text(encoding="utf-8").splitlines() if line.strip()}
    if not pilot:
        raise SystemExit(f"{main} lists no hospitals")
    return pilot


def draw(n: int, seed: int) -> tuple[list[str], int]:
    """n dev hospitals at random (fixed seed) from the dev working set minus the pilot hospitals."""
    pilot = pilot_ids()
    pool = sorted(set(working_set("dev")) - pilot)
    if len(pool) < n:
        raise SystemExit(f"only {len(pool)} non-pilot dev hospitals; cannot draw {n}")
    ids = sorted(random.Random(seed).sample(pool, n))
    assert not set(ids) & pilot
    return ids, len(pilot)


def stop_at(budget: float, workers: int, max_call: float = MAX_CALL_USD) -> float:
    """Spending at which the run stops: the budget minus what the calls still in flight could add (each process may
    be in the middle of one call, up to max_call), so the total stays at or under the budget. The ledger is read
    every 30 s and a stopped call may still be billed by the provider, so this leaves room for both."""
    return budget - workers * max_call


def from_file(path: Path, set_name: str = "dev") -> list[str]:
    """Hospital ids listed in a file (one per line), for a run that picks its hospitals instead of drawing them.
    All from one working set (dev unless `--set eval` says otherwise: an eval run is measured, never tuned on), never a
    pilot hospital; the file belongs under runs/ or the scratchpad (ids stay out of git)."""
    ids = sorted({line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()})
    if not ids:
        raise SystemExit(f"{path} lists no hospitals")
    outside = set(ids) - set(working_set(set_name))
    if outside:
        raise SystemExit(f"{len(outside)} id(s) in {path} are not {set_name} working-set hospitals (--set {set_name})")
    if set(ids) & pilot_ids():
        raise SystemExit(f"{path} lists pilot hospitals; refusing to ask them")
    return ids


def sizes(ids: list[str]) -> tuple[dict[str, int], list[dict]]:
    """Prompt size per hospital, without a model call; and the hospitals too large for one call."""
    from hfal.ask import TooLarge, ask_hospital
    chars, too_large = {}, []
    for hid in ids:
        try:
            chars[hid] = ask_hospital(hid, "dry-run", dry_run=True)["prompt_chars"]
        except TooLarge as e:
            too_large.append({**e.item, "reason": "too_large"})
    return chars, too_large


def deal(chars: dict[str, int], ids: list[str], workers: int) -> list[list[str]]:
    """Largest prompts first, dealt round-robin, so each process gets a similar share of the work."""
    order = sorted(ids, key=lambda h: -chars.get(h, 0))
    return [s for s in (order[i::workers] for i in range(workers)) if s]


def estimate_usd(chars: dict[str, int], ids: list[str]) -> float | None:
    from hfal.usage import price_for
    cfg = paths.settings()["model"]
    p = price_for(provider(cfg), model_id(cfg))
    if not p:
        return None
    tin = sum(chars.get(h, 0) for h in ids) / CHARS_PER_TOKEN
    return (tin * p["input"] + len(ids) * EST_OUTPUT_TOKENS * p["output"]) / 1_000_000


def expectations(run_id: str) -> dict:
    cfg = paths.settings()
    return {"run_id": run_id, "provider": provider(cfg["model"]), "model": model_id(cfg["model"]),
            "prompt_version": cfg["prompt_version"], "effort": cfg["model"].get("effort"),
            "criteria": [c["id"] for c in paths.criteria()], "consistency": bool(paths.consistency_points())}


def ask_cmd(preset: str, run_id: str, ids: list[str]) -> list[str]:
    return ["uv", "run", "hfal", "ask", "--model", preset, "--run-id", run_id, "--hospital", *ids]


def run_processes(groups: list[list[str]], preset: str, run_id: str, label: str, budget: float,
                  max_call: float = MAX_CALL_USD) -> bool:
    """Run one `hfal ask` per group at once; True unless stopped for the budget. Ctrl-C stops them all."""
    logs = paths.RUNS / run_id / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    procs = []
    for i, ids in enumerate(groups, 1):
        log = open(logs / f"{label}_{i}.log", "a", encoding="utf-8")
        procs.append((subprocess.Popen(ask_cmd(preset, run_id, ids), stdout=log, stderr=subprocess.STDOUT), log))
    total = sum(map(len, groups))
    limit = stop_at(budget, len(procs), max_call)
    print(f"{label}: {len(procs)} process(es), {total} hospital(s); logs in {logs}; stops at ${limit:,.2f} spent, "
          f"so calls in flight cannot take it past ${budget:,.2f}")
    within_budget = True
    try:
        while any(p.poll() is None for p, _ in procs):
            time.sleep(30)
            spent = runcheck.spent_usd(run_id)
            done = sum((paths.RUNS / run_id / f"{h}.json").exists() for g in groups for h in g)
            print(f"  {datetime.now():%H:%M:%S}  answer files {done}/{total}  spent ${spent:,.2f}", flush=True)
            if spent > limit:
                print(f"  ${spent:,.2f} spent, near the budget of ${budget:,.2f}: stopping all processes. Answers "
                      f"already received are kept (answer files and the response cache); --resume asks only the rest")
                within_budget = False
                break
    except KeyboardInterrupt:
        print("  interrupted: stopping all processes")
        within_budget = False
    finally:
        for p, log in procs:
            if p.poll() is None:
                p.terminate()
                p.wait()
            log.close()
    for i, (p, _) in enumerate(procs, 1):
        if p.returncode:
            print(f"  process {i} ended with code {p.returncode} (see {logs / f'{label}_{i}.log'})")
    return within_budget


def keep_awake():
    """macOS: keep the Mac from sleeping while this script runs (owner, Nov 12), so no call in flight is cut off.
    `caffeinate -i -s -w PID` blocks idle sleep, and system sleep while on power, until this process ends, then exits
    by itself (also after a budget stop, Ctrl-C or an error). The display may still turn off. Closing the lid still
    sleeps most MacBooks; a call cut off that way is lost (and may be billed), and --resume asks it again.
    Returns the caffeinate process, or None where it does not exist."""
    import os
    import shutil
    if sys.platform != "darwin" or not shutil.which("caffeinate"):
        print("  (not a Mac: sleep is not prevented; keep the computer awake yourself)")
        return None
    print("  keeping the Mac awake until this run ends (caffeinate); keep it plugged in and the lid open")
    return subprocess.Popen(["caffeinate", "-i", "-s", "-w", str(os.getpid())])


def fixable(check: dict) -> list[str]:
    """Hospitals another ask could fix (not those with no documents: asking again changes nothing)."""
    return [h for h, p in check["problems"].items() if not any("no documents collected" in x for x in p)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="kimi-k3-max", help="preset in settings.yaml `models:`")
    ap.add_argument("--prompt-version", default="v7", help="stop unless settings.yaml selects this version")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20261112)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--budget-usd", type=float, default=50.0,
                    help="hard limit for the run's spending (owner, Nov 12: $50); it stops early enough that calls "
                         "in flight stay within it")
    ap.add_argument("--max-call-usd", type=float, default=MAX_CALL_USD,
                    help="the most one call can cost, held back per process before the budget (default: the "
                         "pilot's largest hospital); lower it for a run of small prompts")
    ap.add_argument("--hospitals-file", type=Path, metavar="PATH",
                    help="ask these hospitals (one id per line) instead of drawing --n at random")
    ap.add_argument("--set", dest="set_name", choices=["dev", "eval"], default="dev",
                    help="the working set --hospitals-file must come from (default dev). eval: measured only; "
                         "never read its per-hospital disagreements or tune on it (PLAN.md)")
    ap.add_argument("--report-dir", type=Path, help="where `hfal report` writes (default results/DATE_PRESET_VERSION)")
    ap.add_argument("--retry-rounds", type=int, default=2)
    ap.add_argument("--yes", action="store_true", help="do not ask before spending")
    ap.add_argument("--resume", metavar="RUN_ID")
    ap.add_argument("--check-only", metavar="RUN_ID")
    ap.add_argument("--report-anyway", action="store_true", help="grade and report even if some hospitals failed")
    args = ap.parse_args()

    paths.use_model("model", args.model)
    check_versions()
    cfg = paths.settings()
    if cfg["prompt_version"] != args.prompt_version:
        raise SystemExit(f"settings.yaml selects {cfg['prompt_version']}, not {args.prompt_version}: change "
                         f"--prompt-version or settings.yaml (and criteria_file) first")

    existing = args.resume or args.check_only
    if existing:
        plan_file = paths.RUNS / existing / "final_run.json"
        if not plan_file.exists():
            raise SystemExit(f"{plan_file} not found: was this run started by final_run.py?")
        plan = read_json(plan_file)
        if plan["model_preset"] != args.model:
            raise SystemExit(f"{existing} was asked with --model {plan['model_preset']}; pass the same preset")
        run_id, ids, too_large, chars = existing, plan["hospitals"], plan["too_large"], plan["prompt_chars"]
        check_versions(run_id)
        if set(ids) & pilot_ids():
            raise SystemExit(f"{existing}'s plan includes pilot hospitals; refusing to ask them")
    else:
        if args.hospitals_file:
            ids = from_file(args.hospitals_file, args.set_name)
            print(f"{len(ids)} {args.set_name} hospitals listed in {args.hospitals_file}")
        else:
            ids, n_pilot = draw(args.n, args.seed)
            print(f"{len(ids)} dev hospitals drawn (seed {args.seed}) from the dev working set minus {n_pilot} pilot ids")
        print("building each prompt without calling the model ...")
        chars, too_large = sizes(ids)
        from hfal.ask import new_run_id
        run_id = new_run_id()
        plan = {"run_id": run_id, "model_preset": args.model, "effort": cfg["model"].get("effort"),
                "prompt_version": cfg["prompt_version"], "criteria_file": cfg.get("criteria_file"),
                "seed": None if args.hospitals_file else args.seed, "n": len(ids),
                "selection": f"listed in {args.hospitals_file}" if args.hospitals_file else "random draw",
                "set": args.set_name if args.hospitals_file else "dev",
                "excluded": "pilot hospitals (data/review/pilot_ids*.txt)",
                "workers": args.workers, "budget_usd": args.budget_usd, "max_call_usd": args.max_call_usd,
                "hospitals": ids,
                "too_large": too_large, "prompt_chars": chars,
                "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        asked = [h for h in ids if h in chars]
        est = estimate_usd(chars, asked)
        print(f"model {args.model} (effort {plan['effort']}), prompt {plan['prompt_version']}, run_id {run_id}")
        print(f"to ask: {len(asked)}; too large for one call (recorded, not asked): {len(too_large)}")
        print(f"estimated cost: {'unknown (no price)' if est is None else f'about ${est:,.0f}'} "
              f"(input from prompt size, {EST_OUTPUT_TOKENS:,} output tokens each); hard limit ${args.budget_usd:,.0f} "
              f"(stops at ${stop_at(args.budget_usd, args.workers, args.max_call_usd):,.2f} spent so calls in flight "
              f"stay within it); answers already in the response cache are free and not in this estimate")
        if not args.yes and input("Type yes to start: ").strip().lower() != "yes":
            raise SystemExit("not started; nothing was billed")
        runcheck.save(run_id, "final_run.json", plan)

    expect = expectations(run_id)
    if not args.check_only:
        keep_awake()
        within = True
        todo = [h for h in ids if h in chars and runcheck.check_hospital(runcheck.load(run_id, h), h, expect)]
        if todo:
            if runcheck.spent_usd(run_id) > stop_at(args.budget_usd, args.workers, args.max_call_usd):
                raise SystemExit(f"{run_id} has already spent ${runcheck.spent_usd(run_id):,.2f}, too close to the "
                                 f"budget of ${args.budget_usd:,.2f} to start more calls; raise --budget-usd to go on")
            within = run_processes(deal(chars, todo, args.workers), args.model, run_id, "ask", args.budget_usd,
                                   args.max_call_usd)
        for r in range(1, args.retry_rounds + 1):
            if not within:
                break
            todo = fixable(runcheck.check_run(run_id, ids, expect, too_large))
            if not todo:
                break
            print(f"retry round {r}: {len(todo)} hospital(s) not recorded properly")
            within = run_processes([todo], args.model, run_id, f"retry{r}", args.budget_usd, args.max_call_usd)
            if len(fixable(runcheck.check_run(run_id, ids, expect, too_large))) >= len(todo):
                print("  the retry fixed nothing; not retrying again (each failed call is billed)")
                break

    check = runcheck.check_run(run_id, ids, expect, too_large)
    check["checked_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    check["spent_usd"] = round(runcheck.spent_usd(run_id), 2)
    runcheck.write_run_files(run_id, check, too_large)
    out = runcheck.save(run_id, "final_check.json", check)

    print(f"\n{run_id}")
    print(f"recorded properly: {check['recorded_ok']} of {len(ids)}; too large, not asked: "
          f"{len(check['too_large_not_asked'])}; with a problem: {len(check['problems'])}")
    print(f"billed calls by status: {check['billed_calls_by_status']}; spent ${check['spent_usd']:,.2f}")
    if check["yes_no"]:
        print(f"YES/NO answers with a verified quote: {check['yes_no_quote_verified']} of {check['yes_no']}")
    for h, p in check["problems"].items():
        print(f"  {h}: {'; '.join(p)}")
    if check["stray_files"]:
        print(f"  {len(check['stray_files'])} file(s) in the run folder for hospitals outside the plan")
    print(f"check -> {out}")

    if not check["complete"] and not args.report_anyway:
        print(f"\nNot reported: not every hospital is recorded properly. Fix the cause, then\n"
              f"  uv run python scripts/final_run.py --resume {run_id} --model {args.model}")
        sys.exit(1)
    # its own folder, never results/latest/ (that keeps the report the dashboard already reads)
    report_dir = args.report_dir or Path("results") / f"{datetime.now():%Y-%m-%d}_{args.model}_{cfg['prompt_version']}"
    if report_dir.exists():
        raise SystemExit(f"{report_dir} already exists; not overwriting it")
    for cmd in (["grade", "--run", run_id], ["score", "--run", run_id], ["size-check", "--run", run_id],
                ["report", "--run", run_id, "--out", str(report_dir)], ["usage", "--run", run_id]):
        print(f"\n$ hfal {' '.join(cmd)}", flush=True)
        if subprocess.run(["uv", "run", "hfal", *cmd]).returncode:
            raise SystemExit(f"hfal {cmd[0]} failed")


if __name__ == "__main__":
    main()
