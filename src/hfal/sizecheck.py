"""Long-context check 1: does the error rate climb with the size of the prompt?  `hfal size-check --run RUN_ID`

Why: a hospital's whole text goes to the model in one call. Prompts run from tens of thousands of tokens to a couple
hundred thousand, and research on other models finds accuracy can fall well before the window is full. If the checker
makes more mistakes on the big prompts, that is a warning that something (retrieval, filtering by document type,
splitting the call) is needed. It is a measurement on this model, not an assumption.

What it does
  * Dev hospitals only, from one run. Eval hospitals in the run are skipped and counted (PLAN.md: never tune on eval).
  * Groups: the dev hospitals sorted by prompt size (`prompt_chars` in each run file), cut into three equal thirds,
    plus the hospitals above --big-tokens (default 150,000 tokens, by prompt_chars // 4) as their own group. The
    thirds are made from the hospitals at or under that line. A hospital with no prompt (nothing collected, so no
    model call) is left out.
  * For each group: the hospitals, the prompt-size range, and over every judgment against a YES/NO golden label:
    errors (false YES + false NO; a YES/NO answer that disagrees with the label), flagged (UNCLEAR, NOT_FOUND,
    N/A or an unverified quote; not an error, but not an answer either), with a 95% interval on the error rate that
    resamples whole hospitals (a hospital's judgments are not independent of each other).
    The match rule is `score.score_run`, the same as `hfal score`, so the numbers agree with it.
  * Per criterion and group, counts as errors/judgments, so a small cell cannot pass for a rate.
Counts and rates only: no hospital ids, no labels next to anything. `runs/RUN_ID/size_check.csv` holds the same
aggregates.

Reading it: a rate that climbs from the smallest third to the largest is a warning, not proof (the big prompts may
simply contain harder hospitals: many documents, several applications). A group with fewer than MIN_HOSPITALS
hospitals is marked: its rates are too noisy to read.
"""

import csv
import json
from collections import Counter

from . import paths
from .judge import dev_hospitals
from .score import load_golden, load_run, score_run
from .stats import cluster_ci  # noqa: F401  (also reachable as sizecheck.cluster_ci)

DEFAULT_BIG_TOKENS = 150_000
MIN_HOSPITALS = 10


def prompt_sizes(run_id: str, only: set[str]) -> dict[str, int]:
    """{hospital_id: prompt_chars} for the hospitals in `only` that had a model call in this run."""
    out = {}
    for p in sorted((paths.RUNS / run_id).glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if "answers" in d and d.get("hospital_id") in only and d.get("prompt_chars", 0) > 0:
            out[d["hospital_id"]] = d["prompt_chars"]
    return out


def make_groups(sizes: dict[str, int], big_tokens: int = DEFAULT_BIG_TOKENS) -> list[tuple[str, list[str]]]:
    """[(group name, hospital ids)]: three equal thirds of the hospitals at or under big_tokens, then the big ones."""
    small = sorted((h for h, c in sizes.items() if c // 4 <= big_tokens), key=lambda h: (sizes[h], h))
    big = sorted((h for h, c in sizes.items() if c // 4 > big_tokens), key=lambda h: (sizes[h], h))
    n = len(small)
    thirds = [[h for i, h in enumerate(small) if i * 3 // n == k] for k in range(3)] if n else [[], [], []]
    groups = [(name, ids) for name, ids in zip(["smallest third", "middle third", "largest third"], thirds)]
    groups.append((f"above {big_tokens:,} tokens", big))
    return groups


def tally(ids: list[str], golden: dict, run: dict) -> dict[str, Counter]:
    """Per criterion, for these hospitals: judgments, false_yes, false_no, flagged (via score.score_run)."""
    metrics, _ = score_run({k: v for k, v in golden.items() if k[0] in set(ids)}, {h: run[h] for h in ids})
    out = {}
    for m in metrics:
        n = m["n"]
        out[m["criterion_id"]] = Counter(n=n, false_yes=m["false_yes"], false_no=m["false_no"],
                                         flagged=round((m["flag_rate"] or 0) * n))
    return out


def build(run_id: str, big_tokens: int = DEFAULT_BIG_TOKENS) -> dict:
    run_dir = paths.RUNS / run_id
    if not run_dir.is_dir():
        raise SystemExit(f"{run_dir} not found")
    run = load_run(run_dir)
    dev = dev_hospitals()
    skipped_eval = sum(1 for h in run if h not in dev)
    sizes = prompt_sizes(run_id, dev)
    golden = load_golden(paths.GOLDEN / "golden.csv")
    groups = []
    for name, ids in make_groups(sizes, big_tokens):
        per = tally(ids, golden, run) if ids else {}
        total = Counter()
        for c in per.values():
            total.update(c)
        by_hospital = []
        for h in ids:
            hc = Counter()
            for c in tally([h], golden, run).values():
                hc.update(c)
            by_hospital.append((errors(hc), hc["n"]))
        toks = sorted(sizes[h] // 4 for h in ids)
        groups.append({"name": name, "hospitals": len(ids), "tokens_min": toks[0] if toks else None,
                       "tokens_median": toks[len(toks) // 2] if toks else None, "tokens_max": toks[-1] if toks else None,
                       "total": total, "per_criterion": per,
                       "ci": cluster_ci(by_hospital)})
    return {"run_id": run_id, "groups": groups, "skipped_eval": skipped_eval,
            "no_prompt": sum(1 for h in run if h in dev and h not in sizes), "big_tokens": big_tokens}


def errors(c: Counter) -> int:
    return c["false_yes"] + c["false_no"]


def lines(result: dict) -> list[str]:
    out = [f"Prompt size and error rate, run {result['run_id']} (dev hospitals; judgments against YES/NO golden labels;",
           "interval = 95%, resampling whole hospitals)"]
    out.append(f"  {'group':<22} {'hospitals':>9} {'tokens (min/median/max)':>26} {'judgments':>9} {'errors':>7} "
               f"{'error rate (95% interval)':>27} {'false YES':>9} {'false NO':>8} {'flagged':>8}")
    for g in result["groups"]:
        t = g["total"]
        if not g["hospitals"]:
            out.append(f"  {g['name']:<22} {0:>9}")
            continue
        ci = g["ci"]
        rate = f"{errors(t) / t['n']:.1%} ({ci[0]:.1%}-{ci[1]:.1%})" if ci and t["n"] else (
            f"{errors(t) / t['n']:.1%} (no interval)" if t["n"] else "-")
        flag = f"{t['flagged'] / t['n']:.1%}" if t["n"] else "-"
        out.append(f"  {g['name']:<22} {g['hospitals']:>9} {g['tokens_min']:>9,}/{g['tokens_median']:>7,}/{g['tokens_max']:>7,} "
                   f"{t['n']:>9} {errors(t):>7} {rate:>27} {t['false_yes']:>9} {t['false_no']:>8} {flag:>8}"
                   + ("   (too few hospitals to read)" if g["hospitals"] < MIN_HOSPITALS else ""))
    out.append("")
    out.append("Per criterion: errors/judgments, and flagged in brackets")
    names = [g["name"].replace(" tokens", "") for g in result["groups"]]
    out.append(f"  {'criterion':<62} " + " ".join(f"{n[:14]:>14}" for n in names))
    crits = sorted({c for g in result["groups"] for c in g["per_criterion"]})
    for cid in crits:
        cells = []
        for g in result["groups"]:
            c = g["per_criterion"].get(cid)
            cells.append(f"{errors(c)}/{c['n']} ({c['flagged']})" if c else "-")
        out.append(f"  {cid[:62]:<62} " + " ".join(f"{x:>14}" for x in cells))
    warn = [g["name"] for g in result["groups"] if 0 < g["hospitals"] < MIN_HOSPITALS]
    if warn:
        out.append("")
        out.append(f"Warning: fewer than {MIN_HOSPITALS} hospitals in {', '.join(warn)}. Rates from groups this small "
                   f"are noise; run this on the full dev set.")
    thirds = [g for g in result["groups"][:3] if g["total"]["n"]]
    if len(thirds) >= 2:
        lo, hi = thirds[0], thirds[-1]
        a, b = lo["ci"], hi["ci"]
        if lo["hospitals"] < MIN_HOSPITALS or hi["hospitals"] < MIN_HOSPITALS or not a or not b:
            out.append(f"Not enough hospitals in the smallest and largest thirds (need {MIN_HOSPITALS} each) to compare them.")
        elif b[0] > a[1]:
            out.append("The largest third's error interval lies entirely above the smallest third's: errors rise with "
                       "prompt size. Check whether the big prompts are simply harder hospitals before acting.")
        else:
            out.append("The smallest and largest thirds' error intervals overlap: no size effect is shown by this run.")
    if result["skipped_eval"]:
        out.append(f"{result['skipped_eval']} eval hospital(s) in this run were skipped (dev only).")
    if result["no_prompt"]:
        out.append(f"{result['no_prompt']} dev hospital(s) had no model call (nothing collected) and are left out.")
    return out


def write_csv(result: dict) -> str:
    out = paths.RUNS / result["run_id"] / "size_check.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["group", "criterion", "hospitals", "judgments", "errors", "false_yes", "false_no", "flagged"])
        for g in result["groups"]:
            t = g["total"]
            w.writerow([g["name"], "ALL", g["hospitals"], t["n"], errors(t), t["false_yes"], t["false_no"], t["flagged"]])
            for cid, c in sorted(g["per_criterion"].items()):
                w.writerow([g["name"], cid, g["hospitals"], c["n"], errors(c), c["false_yes"], c["false_no"], c["flagged"]])
    return str(out)
