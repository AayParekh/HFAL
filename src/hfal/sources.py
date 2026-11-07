"""Write the landing-page rows of data/sources.csv from data/hospitals.csv.

`hfal sources --set dev|eval|all` replaces every row labelled "HFA landing page" with one row per URL in
`landing_url` for the hospitals of that set. Rows with any other label (discovered, manual ...) are kept.

Evaluation honesty: eval hospitals must keep the golden sheet's link. If an eval hospital's url_source is
not the golden sheet, this step warns (its score would then reflect our curation, not the pipeline).
"""

import csv
import os
import tempfile

from . import paths

LANDING_LABEL = "HFA landing page"
GOLDEN_SOURCE = "golden sheet (Sept 2025)"
FIELDS = ["hospital_id", "url", "label"]


def load_table() -> list[dict]:
    f = paths.DATA / "hospitals.csv"
    if not f.exists():
        raise SystemExit(f"{f} not found; run: uv run python scripts/seed_hospitals.py")
    with open(f, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if rows and "landing_url" not in rows[0]:
        raise SystemExit(f"{f} has no landing_url column; run: uv run python scripts/seed_hospitals.py")
    return rows


def landing_rows(table: list[dict], set_name: str, only: set[str] | None = None) -> tuple[list[dict], dict]:
    chosen = [h for h in table if (set_name == "all" or h.get("set") == set_name)
              and (only is None or h["hospital_id"] in only)]
    rows = [{"hospital_id": h["hospital_id"], "url": u, "label": LANDING_LABEL}
            for h in chosen for u in h.get("landing_url", "").split()]
    stats = {
        "hospitals_in_set": len(chosen),
        "without_landing_url": sum(not h.get("landing_url", "").strip() for h in chosen),
        "eval_url_not_from_golden": sum(bool(h.get("set") == "eval" and h.get("landing_url", "").strip()
                                             and h.get("url_source") != GOLDEN_SOURCE) for h in chosen),
        "landing_rows": len(rows),
    }
    return rows, stats


def build_sources(set_name: str, only: set[str] | None = None) -> None:
    rows, stats = landing_rows(load_table(), set_name, only)
    src = paths.DATA / "sources.csv"
    existing = []
    if src.exists():
        with open(src, newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    kept = [r for r in existing if r.get("label") != LANDING_LABEL]
    fd, tmp = tempfile.mkstemp(dir=src.parent, suffix=".tmp")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(kept + rows)
    os.replace(tmp, src)
    for k, v in stats.items():
        print(f"{k}: {v}")
    if stats["eval_url_not_from_golden"]:
        print("WARNING: some eval hospitals have hand-edited landing URLs; eval results would reflect curation")
    print(f"kept {len(kept)} other rows; wrote {len(kept) + len(rows)} rows -> {src}")
