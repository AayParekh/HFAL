import argparse
import csv
import json
import random
import re

from pathlib import Path

from . import consistency, corrected, doccheck, monitor, paths, report, sizecheck, usage
from .ask import iter_ask, new_run_id, ping, write_skipped
from .discover import discover_all
from .extract import extract_all
from .fetch import fetch_all
from .grade import grade_hospital
from .judge import judge_run
from .score import load_golden, load_run, score_run, summarize_run, write_csv
from .sources import build_sources
from .tag import tag_all


def _only(values):
    return set(values) if values else None


def working_set(set_name: str = "all") -> list[str]:
    """Hospitals that passed every exclusion check (data/working_set.csv, written by scripts/attrition.py).

    Sites blocked by robots.txt or a bot check, broken links, and documents that need OCR are left out
    on purpose (PLAN.md). Without that file, falls back to every hospital that has extracted text.
    """
    f = paths.DATA / "working_set.csv"
    if not f.exists():
        print("note: data/working_set.csv not found (run scripts/attrition.py); using every hospital with text")
        return sorted(d.name for d in paths.TEXT.iterdir() if d.is_dir())
    with open(f, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    ids = [r["hospital_id"] for r in rows if set_name == "all" or r["set"] == set_name]
    print(f"working set ({set_name}): {len(ids)} hospitals")
    return ids


def pick_sample(ids: list[str], n: int, seed: int) -> list[str]:
    """n hospitals chosen at random with a fixed seed (same ids and seed, same sample; order of ids does not matter)."""
    ids = sorted(ids)
    if n > len(ids):
        raise SystemExit(f"--sample {n} is more than the {len(ids)} hospitals available")
    return sorted(random.Random(seed).sample(ids, n))


def check_versions(run_id: str | None = None) -> None:
    """Stop before a model call when settings.yaml's prompt_version and criteria_file disagree (criteria.yaml is v5,
    criteria_vN.yaml is vN), or when the run being judged was asked with another prompt version than settings say.
    The two settings lines are changed by hand and together; a mismatch would label a run with the wrong version."""
    cfg = paths.settings()
    name = cfg.get("criteria_file", "criteria.yaml")
    m = re.fullmatch(r"criteria_(v\d+)\.yaml", name)
    expected = m.group(1) if m else ("v5" if name == "criteria.yaml" else None)
    if expected and cfg["prompt_version"] != expected:
        raise SystemExit(f"settings.yaml: prompt_version is {cfg['prompt_version']} but criteria_file is {name} "
                         f"({expected}); change both together")
    if run_id and not run_id.endswith("_" + cfg["prompt_version"]):
        raise SystemExit(f"run {run_id} was not asked with prompt_version {cfg['prompt_version']} (settings.yaml); "
                         f"set prompt_version and criteria_file to the run's version first")


def run_ask(ids: list[str], run_id: str, dry_run: bool = False) -> list[dict]:
    """Ask each hospital (the body of `hfal ask`, also used by `hfal monitor`). Returns the hospitals skipped as too
    large. Prints the usage summary and writes runs/RUN_ID/usage.json even when an error stops it part-way."""
    skipped = []
    totals = usage.Totals()
    try:
        for hid, r, skip in iter_ask(ids, run_id, dry_run=dry_run):
            if skip:
                skipped.append(skip)
                print(f"{hid}  SKIPPED too large for one call  about {skip['est_tokens']} tokens, "
                      f"limit {skip['limit_tokens']}")
            elif dry_run:
                print(f"{hid}  documents={r.get('documents', 0)}  approx_input_tokens={r.get('approx_input_tokens', 0)}")
            else:
                c = r.get("call") or {}
                totals.add(c)
                print(f"{hid}  done  input_tokens={c.get('input_tokens')}  output_tokens={c.get('output_tokens')}"
                      f"  cached={c.get('cached')}")
    finally:       # an error part-way still reports what was spent before it (the ledger has every billed call)
        if not dry_run and (totals.fresh or totals.cached):
            usage.write_run_usage(run_id, "ask", totals)
            print("\n".join(totals.lines("ask usage")))
    if not dry_run:
        write_skipped(run_id, skipped)
    return skipped


def grade_run(run_id: str) -> None:
    """runs/RUN_ID/grades.csv (the body of `hfal grade`, also used by `hfal monitor`)."""
    run_dir = paths.RUNS / run_id
    rubric = paths.rubric()
    ids = [c["id"] for c in paths.criteria()]
    rows = []
    for hid, recs in load_run(run_dir).items():
        g = grade_hospital(recs, ids, rubric)
        full = json.loads((run_dir / f"{hid}.json").read_text(encoding="utf-8"))
        rep = full.get("reported", {})
        verified = lambda key, field: "; ".join(sorted({x[field].strip().title() for x in rep.get(key, [])  # noqa: E731
                                                         if x.get("quote_verified")}))
        rows.append(dict(
            hospital_id=hid, status=g["status"], letter=g["letter"] or "",
            errors=g["errors"], confirmed_errors=g["confirmed_errors"], auto_fail=";".join(g["auto_fail"]),
            yes=g["counts"]["YES"], no=g["counts"]["NO"], na=g["counts"]["N/A"],
            needs_review=g["counts"]["needs_review"],
            failing=";".join(g["failing"]), review_ids=";".join(g["needs_review"]),
            **{f"reported_{k}": v for k, v in g["reported"].items()},
            languages=verified("languages", "language"),
            languages_from_links="; ".join(rep.get("languages_from_links", [])),
            psa_counties=verified("psa_counties", "county"),
        ))
    write_csv(run_dir / "grades.csv", rows)
    print(f"wrote {run_dir / 'grades.csv'}")


def run_monitor(requested: list[str] | None, ask: bool) -> None:
    """`hfal monitor`: refresh and compare every dev working hospital, then ask and grade only those that changed."""
    if ask:
        check_versions()        # stop before any fetching if the prompt settings disagree
    ids = monitor.select_ids(requested, working_set(monitor.MONITORED_SET))
    results = monitor.check(ids)
    cfg = paths.settings()
    meta = {"checked_on": results[0]["checked_on"] if results else "", "set": monitor.MONITORED_SET,
            "hospitals": len(results), "not_monitored": monitor.not_monitored(), "prompt_version": cfg["prompt_version"],
            "run_id": None, "ask_note": "" if ask else "--no-ask"}
    if not results:
        print("no hospitals to check")
        return
    monitor.add_results(results, None, cfg["prompt_version"])
    monitor.write_report(results, meta)        # the change report is saved before any model call
    changed = [r["hospital_id"] for r in results if r["status"] == "changed"]
    if ask and changed:
        run_id = new_run_id()
        meta["run_id"] = run_id
        try:
            run_ask(changed, run_id)
            grade_run(run_id)
        finally:                               # a failed ask still leaves a report of what was asked
            monitor.add_results(results, run_id, cfg["prompt_version"])
            monitor.write_report(results, meta)
            (paths.RUNS / run_id).mkdir(parents=True, exist_ok=True)
            (paths.RUNS / run_id / "monitor.json").write_text(json.dumps(
                {"checked_on": meta["checked_on"], "set": meta["set"], "asked": changed}), encoding="utf-8")
    print("\n".join(monitor.lines(results, meta)))


def main() -> None:
    p = argparse.ArgumentParser(prog="hfal")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", help="tiny request to check the model provider's credentials and model access")
    s = sub.add_parser("sources", help="write landing-page rows of data/sources.csv from data/hospitals.csv")
    s.add_argument("--set", choices=["dev", "eval", "all"], default="dev")
    s.add_argument("--hospital", nargs="*", help="limit to these hospital_ids")
    for name in ("discover", "fetch", "extract", "tag"):
        s = sub.add_parser(name)
        s.add_argument("--hospital", nargs="*", help="limit to these hospital_ids")
    s = sub.add_parser("ask")
    s.add_argument("--hospital", nargs="*")
    s.add_argument("--run-id")
    s.add_argument("--dry-run", action="store_true", help="report prompt size per hospital; no model call")
    s.add_argument("--set", choices=["dev", "eval", "all"], default="all",
                   help="which part of the working set to ask when --hospital is not given (default: all)")
    s.add_argument("--sample", type=int, help="ask only N hospitals chosen at random from the set (needs --seed)")
    s.add_argument("--seed", type=int, help="seed for --sample, so the same hospitals can be asked again")
    s = sub.add_parser("judge", help="explain the disagreements with the golden labels (dev hospitals only)")
    s.add_argument("--run", required=True, help="run_id folder under runs/")
    s.add_argument("--hospital", nargs="*", help="limit to these hospital_ids")
    s.add_argument("--dry-run", action="store_true", help="count disagreements and prompt size; no model call")
    s = sub.add_parser("doc-check", help="count doc_not_found rows and missing document types (discovery check)")
    s.add_argument("--run", help="run_id that `hfal judge` has been run on (adds the doc_not_found counts)")
    s.add_argument("--min-rows", type=int, default=doccheck.DEFAULT_MIN_ROWS,
                   help="doc_not_found rows that make a dev hospital a suspect (default 2)")
    s = sub.add_parser("size-check", help="error rate by prompt size (long-context check 1; dev hospitals only)")
    s.add_argument("--run", required=True, help="run_id folder under runs/")
    s.add_argument("--big-tokens", type=int, default=sizecheck.DEFAULT_BIG_TOKENS,
                   help="hospitals with a prompt above this many tokens form their own group (default 150000)")
    s = sub.add_parser("consistency-check",
                       help="consistency point by point: conflicts per point and what-if scores (v7 runs; dev only)")
    s.add_argument("--run", required=True, help="run_id folder under runs/")
    s = sub.add_parser("usage", help="add up tokens and cost from the ledger (runs/usage.csv)")
    s.add_argument("--by", choices=["purpose", "model", "day", "run", "status"], default="purpose")
    s.add_argument("--since", help="only calls on or after this date, YYYY-MM-DD (UTC)")
    s.add_argument("--run", help="only this run_id")
    s = sub.add_parser("monitor", help="monthly check of the dev working hospitals: fetch and discover again, report "
                                       "new / changed / removed / unreachable documents, ask and grade only those that changed")
    s.add_argument("--hospital", nargs="*", help="limit to these hospital_ids (dev hospitals of the working set only)")
    s.add_argument("--no-ask", action="store_true", help="report the changes only; no model call")
    for name in ("grade", "score"):
        s = sub.add_parser(name)
        s.add_argument("--run", required=True, help="run_id folder under runs/")
        if name == "score":
            s.add_argument("--corrected", help="corrected-labels file to score against as well "
                                               "(default data/review/corrected_labels.csv, when it exists)")
    s = sub.add_parser("report", help="readable results (CSV + HTML) with plain-language explanations, from one or "
                                      "more runs; no model call, no golden labels")
    s.add_argument("--run", action="append", required=True, help="run_id folder under runs/; repeat for several runs")
    s.add_argument("--out", help="output folder (default data/report/TODAY/)")
    args = p.parse_args()

    if args.cmd == "ping":
        r = ping(paths.settings()["model"])
        print(f"ok: {r['provider']}  model={r['model_id']}  region={r['region'] or '-'}  "
              f"reply={r['reply']!r}  tokens={r['input_tokens']}/{r['output_tokens']}")
    elif args.cmd == "sources":
        build_sources(args.set, only=_only(args.hospital))
    elif args.cmd == "discover":
        discover_all(only=_only(args.hospital))
    elif args.cmd == "fetch":
        fetch_all(only=_only(args.hospital))
    elif args.cmd == "extract":
        extract_all(only=_only(args.hospital))
    elif args.cmd == "tag":
        tag_all(only=_only(args.hospital))
    elif args.cmd == "ask":
        check_versions()
        run_id = args.run_id or new_run_id()
        ids = args.hospital or working_set(args.set)
        if args.sample:
            if args.seed is None:
                raise SystemExit("--sample needs --seed, so the same hospitals can be chosen again")
            if args.set == "eval":
                raise SystemExit("sampling is for dev; the eval set is asked whole, at a checkpoint (PLAN.md)")
            ids = pick_sample(ids, args.sample, args.seed)
        skipped = run_ask(ids, run_id, dry_run=args.dry_run)
        if not args.dry_run:
            if args.sample:
                (paths.RUNS / run_id).mkdir(parents=True, exist_ok=True)
                (paths.RUNS / run_id / "sample.json").write_text(
                    json.dumps({"set": args.set, "n": args.sample, "seed": args.seed}), encoding="utf-8")
            print(f"run_id: {run_id}")
        print(f"asked {len(ids) - len(skipped)} of {len(ids)} hospitals; skipped as too large: {len(skipped)}")
    elif args.cmd == "judge":
        check_versions(args.run)
        print(json.dumps(judge_run(args.run, only=_only(args.hospital), dry_run=args.dry_run), indent=2))
    elif args.cmd == "doc-check":
        if args.run and not (paths.RUNS / args.run).is_dir():
            raise SystemExit(f"{paths.RUNS / args.run} not found")
        result = doccheck.build(working_set("dev"), working_set("eval"), args.run, min_rows=args.min_rows)
        print("\n".join(doccheck.lines(result)))
        if args.run:
            where = doccheck.write_csv(args.run, result["dev_rows"])
        else:
            where = doccheck.write_csv_to(paths.DATA / "review" / "doc_check.csv", result["dev_rows"])
        print(f"dev rows (hospital ids, no labels) -> {where}")
    elif args.cmd == "size-check":
        result = sizecheck.build(args.run, args.big_tokens)
        print("\n".join(sizecheck.lines(result)))
        print(f"aggregates -> {sizecheck.write_csv(result)}")
    elif args.cmd == "consistency-check":
        if not (paths.RUNS / args.run).is_dir():
            raise SystemExit(f"{paths.RUNS / args.run} not found")
        result = consistency.build(args.run)
        print("\n".join(consistency.lines(result)))
        print(f"aggregates -> {consistency.write_csv(result)}")
    elif args.cmd == "usage":
        print("\n".join(usage.report(since=args.since, run=args.run, by=args.by)))
    elif args.cmd == "monitor":
        run_monitor(args.hospital, ask=not args.no_ask)
    elif args.cmd == "grade":
        grade_run(args.run)
    elif args.cmd == "report":
        report.write(args.run, Path(args.out) if args.out else None)
    elif args.cmd == "score":
        run_dir = paths.RUNS / args.run
        golden = load_golden(paths.GOLDEN / "golden.csv")
        run = load_run(run_dir)
        metrics, diffs = score_run(golden, run)
        write_csv(run_dir / "metrics.csv", metrics)
        write_csv(run_dir / "diff.csv", diffs)
        pc = lambda x: "-" if x is None else f"{x:.2f}"  # noqa: E731

        def table(title, rows):
            print(title)
            print(f"{'criterion':<62} {'n':>4} {'falseYES':>8} {'falseNO':>7} {'flag':>5} {'precYES':>7} {'recYES':>6} {'precNO':>6} {'recNO':>5}")
            for m in rows:
                print(f"{m['criterion_id'][:62]:<62} {m['n']:>4} {m['false_yes']:>8} {m['false_no']:>7} {pc(m['flag_rate']):>5} "
                      f"{pc(m['precision_yes']):>7} {pc(m['recall_yes']):>6} {pc(m['precision_no']):>6} {pc(m['recall_no']):>5}")
            print()

        table("PER CRITERION, AGAINST CSSNY'S SHEET AS IT IS", metrics)
        cfile = Path(args.corrected) if args.corrected else corrected.FILE
        fixes = corrected.load(cfile)
        if fixes and corrected.counts(fixes, set(run))["rows"]:
            cmetrics, _ = score_run(corrected.apply(golden, fixes), run)
            write_csv(run_dir / "metrics_corrected.csv", cmetrics)
            table("PER CRITERION, AGAINST CORRECTED LABELS (reviewed disagreements only; see below)", cmetrics)
        lines, summary = summarize_run(args.run, cfile)
        print("\n".join(lines))
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\n{len(diffs)} disagreements -> {run_dir / 'diff.csv'} (dev rows only may be read; never eval rows)")
        print(f"per-criterion metrics -> {run_dir / 'metrics.csv'}"
              + (f" and {run_dir / 'metrics_corrected.csv'}" if "corrected" in summary else "")
              + f"; pooled and letter summary -> {run_dir / 'summary.json'}")

if __name__ == "__main__":
    main()
