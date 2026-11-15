"""Do the hospitals we measured look like the rest of the state?  Aggregates only, no model call, no cost.

    uv run python scripts/representativeness.py [--final-run RUN_ID] [--resamples 10000]

Four comparisons, each "this group" against "every other hospital among the 211":
  * pilot 15       the hand-reviewed hospitals (data/review/pilot_ids*.txt); v7 was partly written from them
  * random 40      the final run's 40 dev hospitals, drawn at random (the headline numbers)
  * dev 85         the dev hospitals in the working set
  * working 132    the hospitals whose documents we could collect, against the 79 we could not

Features exist for all 211 hospitals and come from CSSNY's sheet and our hospital table, never from model results:
NYC (the sheet's "NYC?" column; blank is read as not NYC), part of a health system with 2+ hospitals among the 211,
CSSNY's letter as grade points (A=4 ... F=0), share with A or B, automatic fail, CSSNY's noncompliant count, and the
share of a hospital's YES/NO labels that are YES.

Per feature: group mean, mean of the others, the difference with a 95% bootstrap interval (each group resampled on its
own), the standardized difference (difference / pooled SD; under 0.1 is small, over 0.25 is worth a look), and a
two-sided permutation p-value. 4 comparisons x 7 features = 28 tests, so one or two p < 0.05 are expected by chance.

Reading it: "no difference detected" is not "the same". The interval says how big a gap the data can rule out.

Data handling: prints group sizes, means and counts only. Never a hospital id or a label next to a hospital. Uses
golden labels of eval hospitals in aggregate only (no model results on eval, nothing tuned). Writes the same numbers
to data/review/representativeness.csv (git-ignored).
"""

import argparse
import csv
import json
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FINAL_RUN = "20261113T045436Z_openweight_us-moonshotai-kimi-k3_v7"
SEED = 20261113
POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
LETTERS = ["A", "B", "C", "D", "F"]


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:  # the review sheets were saved by Numbers with a BOM
        return list(csv.DictReader(f))


def row_check(final_run: str, rng: random.Random, resamples: int) -> list[str]:
    """Are the 20 reviewed rows a typical random draw from the 40's YES/NO disagreements?

    Compares the sample's criterion mix with every YES/NO disagreement in the run's diff.csv (as it is now, after
    rule B), by total variation distance (half the summed absolute differences in shares). The p-value is the share
    of simulated draws, made the way the sample was (same number of model-YES and model-NO rows, at random), whose
    distance is at least as large. Counts per criterion only."""
    diff = [r for r in read_csv(ROOT / "runs" / final_run / "diff.csv")
            if r["golden"] in ("YES", "NO") and r["effective"] in ("YES", "NO") and r["golden"] != r["effective"]]
    keys = {(r["hospital_id"], r["criterion_id"]) for r in diff}
    sample = read_csv(ROOT / "data/review/final40_sample_review.csv")
    in_pool = [r for r in sample if (r["hospital_id"], r["criterion_id"]) in keys]
    pool_by_dir = {d: [r["criterion_id"] for r in diff if r["effective"] == d] for d in ("YES", "NO")}
    n_dir = Counter(r["model_answer"] for r in sample)
    pool = Counter(r["criterion_id"] for r in diff)

    def tvd(c: Counter, n: int) -> float:
        return 0.5 * sum(abs(c[k] / n - pool[k] / len(diff)) for k in pool | c)

    observed = tvd(Counter(r["criterion_id"] for r in sample), len(sample))
    hits = 0
    for _ in range(resamples):
        draw = Counter()
        for d, k in n_dir.items():
            draw.update(rng.sample(pool_by_dir[d], k))
        hits += tvd(draw, len(sample)) >= observed - 1e-12
    hospitals = Counter(r["hospital_id"] for r in sample)
    out = [f"== reviewed rows: the 40's sample of {len(sample)} vs all {len(diff)} YES/NO disagreements in the run",
           f"  model said YES / NO: sample {n_dir['YES']} / {n_dir['NO']}, all "
           f"{len(pool_by_dir['YES'])} / {len(pool_by_dir['NO'])}",
           f"  sample rows still a YES/NO disagreement after rule B: {len(in_pool)} of {len(sample)}",
           f"  rows per hospital in the sample: {len(hospitals)} hospitals, at most {max(hospitals.values())} rows from one",
           f"  criterion mix, distance from all disagreements {observed:.2f}; p = {(hits + 1) / (resamples + 1):.3f} "
           f"(share of random draws as far or farther)",
           f"  {'criterion':64} {'sample':>6} {'all':>5}"]
    sample_c = Counter(r["criterion_id"] for r in sample)
    for k, v in pool.most_common():
        out.append(f"  {k:64} {sample_c[k]:6d} {v:5d}")
    return out


def nyc_flags(path: Path) -> dict[str, float]:
    """{hospital_id: 1.0 if the sheet's NYC? column says nyc else 0.0} from the two-header-row raw sheet."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = rows[1]
    i_id, i_nyc = header.index("Permanent Facility Identifier (PFI)"), header.index("NYC?")
    return {r[i_id].strip(): float(r[i_nyc].strip().lower() == "nyc") for r in rows[2:] if len(r) > i_id and r[i_id].strip()}


def features() -> dict[str, dict[str, float]]:
    """{hospital_id: {feature: value}} for the 211 hospitals."""
    hospitals = read_csv(ROOT / "data/hospitals.csv")
    system_size = Counter(r["system"].strip() for r in hospitals)
    grades = {r["hospital_id"]: r for r in read_csv(ROOT / "golden/golden_grades.csv")}
    nyc = nyc_flags(ROOT / "golden/golden_raw.csv")
    yes, yesno = Counter(), Counter()
    for r in read_csv(ROOT / "golden/golden.csv"):
        label = r["label"].strip().upper()
        if label in ("YES", "NO"):
            yesno[r["hospital_id"]] += 1
            yes[r["hospital_id"]] += label == "YES"
    out = {}
    for r in hospitals:
        h, g = r["hospital_id"], grades[r["hospital_id"]]
        out[h] = {
            "NYC": nyc[h],
            "in a system of 2+ hospitals": float(system_size[r["system"].strip()] >= 2),
            "CSSNY grade points (A=4, F=0)": float(POINTS[g["letter"]]),
            "CSSNY letter A or B": float(g["letter"] in ("A", "B")),
            "CSSNY automatic fail": float(g["auto_fail"].strip().upper() == "TRUE"),
            "CSSNY noncompliant count": float(g["noncompliant_count"]),
            "share of YES/NO labels that are YES": yes[h] / yesno[h] if yesno[h] else float("nan"),
        }
    return out


def groups(final_run: str) -> dict[str, set[str]]:
    pilot = set()
    for p in sorted((ROOT / "data/review").glob("pilot_ids*.txt")):
        pilot |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    random40 = set()
    for p in (ROOT / "runs" / final_run).glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        if "answers" in d and "hospital_id" in d:
            random40.add(d["hospital_id"])
    sample40 = {r["hospital_id"] for r in read_csv(ROOT / "data/review/final40_sample_review.csv")}
    not_found = {h for r in read_csv(ROOT / "data/review/not_found_review.csv") if r["human_finding"].strip()
                 for h in r["hospital_ids"].split()}
    reviewed = pilot | sample40 | not_found
    working = read_csv(ROOT / "data/working_set.csv")
    return {
        f"all hand-reviewed {len(reviewed)} (pilot + 40's sample + NOT_FOUND checks)": reviewed,
        f"40's review sample {len(sample40)}": sample40,
        f"fill run NOT_FOUND checks {len(not_found)}": not_found,
        f"pilot {len(pilot)}": pilot,
        f"random {len(random40)}": random40,
        f"dev {sum(r['set'] == 'dev' for r in working)}": {r["hospital_id"] for r in working if r["set"] == "dev"},
        f"working {len(working)}": {r["hospital_id"] for r in working},
    }


def compare(a: list[float], b: list[float], rng: random.Random, resamples: int) -> dict:
    diff = statistics.fmean(a) - statistics.fmean(b)
    boot = sorted(statistics.fmean(rng.choices(a, k=len(a))) - statistics.fmean(rng.choices(b, k=len(b)))
                  for _ in range(resamples))
    pooled_sd = (((len(a) - 1) * statistics.variance(a) + (len(b) - 1) * statistics.variance(b))
                 / (len(a) + len(b) - 2)) ** 0.5
    both, n, extreme = a + b, len(a), 0
    for _ in range(resamples):
        rng.shuffle(both)
        extreme += abs(statistics.fmean(both[:n]) - statistics.fmean(both[n:])) >= abs(diff) - 1e-12
    return {
        "group_mean": statistics.fmean(a), "rest_mean": statistics.fmean(b), "diff": diff,
        "lo": boot[int(0.025 * resamples)], "hi": boot[int(0.975 * resamples) - 1],
        "smd": diff / pooled_sd if pooled_sd else 0.0, "p": (extreme + 1) / (resamples + 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--final-run", default=DEFAULT_FINAL_RUN)
    ap.add_argument("--resamples", type=int, default=10000)
    args = ap.parse_args()
    if not (ROOT / "golden/golden.csv").exists():
        sys.exit("golden/ is missing: this script needs CSSNY's files (see docs/technical.md)")

    feats = features()
    everyone = set(feats)
    rng = random.Random(SEED)
    rows = []
    print(f"All hospitals: {len(everyone)}. Each group is compared with every other hospital among them.")
    print("diff = group minus others, 95% bootstrap interval; SMD = standardized difference; p = permutation, two-sided\n")
    names = list(next(iter(feats.values())))
    for gname, ids in groups(args.final_run).items():
        ids &= everyone
        rest = everyone - ids
        print(f"== {gname} vs other {len(rest)}")
        print(f"  {'feature':38} {'group':>7} {'others':>7} {'diff (95% interval)':>26} {'SMD':>6} {'p':>6}")
        for f in names:
            a = [feats[h][f] for h in sorted(ids) if feats[h][f] == feats[h][f]]
            b = [feats[h][f] for h in sorted(rest) if feats[h][f] == feats[h][f]]
            c = compare(a, b, rng, args.resamples)
            print(f"  {f:38} {c['group_mean']:7.2f} {c['rest_mean']:7.2f} "
                  f"{c['diff']:+8.2f} ({c['lo']:+6.2f} to {c['hi']:+6.2f}) {c['smd']:+6.2f} {c['p']:6.3f}")
            rows.append({"group": gname, "group_n": len(a), "others_n": len(b), "feature": f,
                         **{k: round(v, 4) for k, v in c.items()}})
        counts_g = Counter(feats[h]["CSSNY grade points (A=4, F=0)"] for h in ids)
        counts_r = Counter(feats[h]["CSSNY grade points (A=4, F=0)"] for h in rest)
        fmt = lambda c, n: "  ".join(f"{L} {100 * c[float(POINTS[L])] / n:4.0f}%" for L in LETTERS)
        print(f"  CSSNY letters, group : {fmt(counts_g, len(ids))}")
        print(f"  CSSNY letters, others: {fmt(counts_r, len(rest))}\n")

    print("\n".join(row_check(args.final_run, rng, args.resamples)) + "\n")
    out = ROOT / "data/review/representativeness.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"aggregates -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
