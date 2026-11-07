"""Seed data/hospitals.csv, the hospital table we own, from the golden sheet. Add-only.

    uv run python scripts/seed_hospitals.py [--golden CSV] [--sample CSV] [--dst CSV]

data/hospitals.csv columns
    hospital_id   PFI
    name, city, system   from the golden sheet's identity columns
    set           dev (in data/sample_raw.csv) or eval (every other golden hospital)
    landing_url   where discovery starts; several URLs separated by spaces
    url_source    where landing_url came from: "golden sheet (Sept 2025)", or who/what changed it
    verified_at   date someone last confirmed landing_url works (YYYY-MM-DD), blank if never
    note          free text (e.g. "golden HFA Link cell has no URL", "site moved to ...")

Rules
    - Add-only: a hospital already in the table is never changed. Edit the table by hand (or later the front
      end) to fix a link, and set url_source / verified_at / note when you do.
    - Exception: a column missing from an older table is filled in from the golden sheet once.
    - Hospitals in the table but not in the golden sheet are kept.

Reads ONLY identity columns of the golden sheet ("Permanent Facility Identifier (PFI)", "Hospital Name",
"City", "System", "HFA Link"); no labels, grades or notes. Prints counts only.
"""

import argparse
import csv
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from hfal.schema import hospital_id

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["hospital_id", "name", "city", "system", "set", "landing_url", "url_source", "verified_at", "note"]
GOLDEN_SOURCE = "golden sheet (Sept 2025)"
COLS = {"hospital_id": "Permanent Facility Identifier (PFI)", "name": "Hospital Name", "city": "City",
        "system": "System", "link": "HFA Link"}


def clean_urls(cell: str, stats: Counter) -> list[str]:
    """URLs found in a link cell. A token counts only if it starts with http(s):// or www.
    A cell that is a single bare domain (example.org/path) also counts. Any other text is ignored,
    so a cell holding only a sentence yields no URL."""
    tokens = [t for t in re.split(r"[\s;]+", cell.strip()) if t]
    urls = []
    for t in tokens:
        if re.match(r"https?://", t, re.I):
            pass
        elif re.match(r"www\.", t, re.I) or (len(tokens) == 1 and re.match(r"[\w-]+(\.[\w-]+)+(/|$)", t)):
            t = "https://" + t
            stats["scheme_added"] += 1
        else:
            continue
        if "." in urlparse(t).netloc:
            urls.append(t.rstrip(".,)"))
        else:
            stats["invalid_links"] += 1
    if len(urls) > 1:
        stats["cells_with_several_links"] += 1
    if not urls:
        stats["cells_without_url"] += 1
    return urls


def read_golden(path: Path, stats: Counter) -> list[dict]:
    """One dict per hospital: hospital_id, name, city, system, urls. First row wins on duplicate PFIs."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if len(rows) < 3:
        raise SystemExit(f"{path}: expected two header rows and data")
    names = [n.strip() for n in rows[1]]  # row 1 holds group labels, row 2 the column names
    missing = [c for c in COLS.values() if c not in names]
    if missing:
        raise SystemExit(f"{path}: column(s) not found in the second header row: {missing}")
    idx = {k: names.index(v) for k, v in COLS.items()}
    cell = lambda r, k: r[idx[k]] if idx[k] < len(r) else ""

    out, seen = [], set()
    for r in rows[2:]:
        if not any(c.strip() for c in r):
            continue
        stats["golden_rows"] += 1
        hid = hospital_id(cell(r, "hospital_id"))
        if not hid:
            stats["golden_rows_without_pfi"] += 1
            continue
        if hid in seen:
            stats["golden_duplicate_pfi_rows"] += 1
            continue
        seen.add(hid)
        link = cell(r, "link")
        out.append({"hospital_id": hid, "name": cell(r, "name").strip(), "city": cell(r, "city").strip(),
                    "system": cell(r, "system").strip(), "urls": clean_urls(link, stats) if link.strip() else []})
    return out


def read_sample_ids(path: Path) -> set[str]:
    """PFIs from the sample sheet. The header row is found by looking for 'Hospital' and 'PFI' cells."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    for idx, r in enumerate(rows):
        cells = [c.strip() for c in r]
        if "PFI" in cells and "Hospital" in cells:
            col = cells.index("PFI")
            return {i for i in (hospital_id(x[col]) for x in rows[idx + 1:] if len(x) > col) if i}
    raise SystemExit(f"{path}: no header row with 'Hospital' and 'PFI' cells")


def from_golden(g: dict, dev_ids: set[str] | None) -> dict:
    return {
        "hospital_id": g["hospital_id"], "name": g["name"], "city": g["city"], "system": g["system"],
        "set": "" if dev_ids is None else ("dev" if g["hospital_id"] in dev_ids else "eval"),
        "landing_url": " ".join(g["urls"]),
        "url_source": GOLDEN_SOURCE if g["urls"] else "",
        "verified_at": "",
        "note": "" if g["urls"] else "golden HFA Link cell has no URL",
    }


def seed(existing: list[dict], existing_fields: list[str], golden: list[dict],
         dev_ids: set[str] | None) -> tuple[list[dict], Counter]:
    stats = Counter()
    by_id = {r["hospital_id"]: dict(r) for r in existing}
    missing_cols = [f for f in FIELDS if f not in existing_fields]
    for g in golden:
        fresh = from_golden(g, dev_ids)
        if g["hospital_id"] not in by_id:
            by_id[g["hospital_id"]] = fresh
            stats["added"] += 1
            continue
        row = by_id[g["hospital_id"]]
        for f in missing_cols:               # an older table without this column: fill it once
            row[f] = fresh[f]
        if missing_cols:
            stats["filled_new_columns"] += 1
        else:
            stats["kept_unchanged"] += 1
        if row.get("url_source") not in (GOLDEN_SOURCE, ""):
            stats["landing_url_edited_by_hand"] += 1
    golden_ids = {g["hospital_id"] for g in golden}
    stats["in_table_not_in_golden"] = sum(h not in golden_ids for h in by_id)
    key = lambda h: (0, int(h)) if h.isdigit() else (1, h)
    rows = [{f: by_id[h].get(f, "") for f in FIELDS} for h in sorted(by_id, key=key)]
    stats["hospitals"] = len(rows)
    stats["dev"] = sum(r["set"] == "dev" for r in rows)
    stats["eval"] = sum(r["set"] == "eval" for r in rows)
    stats["without_landing_url"] = sum(not r["landing_url"] for r in rows)
    return rows, stats


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--golden", type=Path, default=ROOT / "golden" / "golden_raw.csv")
    p.add_argument("--sample", type=Path, default=ROOT / "data" / "sample_raw.csv")
    p.add_argument("--dst", type=Path, default=ROOT / "data" / "hospitals.csv")
    args = p.parse_args()

    stats = Counter()
    golden = read_golden(args.golden, stats)
    dev_ids = read_sample_ids(args.sample) if args.sample.exists() else None
    if dev_ids is None:
        print(f"note: {args.sample} not found; 'set' left blank for new hospitals")

    existing, fields = [], []
    if args.dst.exists():
        with open(args.dst, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = list(reader.fieldnames or [])
            existing = list(reader)
    rows, s = seed(existing, fields, golden, dev_ids)
    stats.update(s)

    fd, tmp = tempfile.mkstemp(dir=args.dst.parent, suffix=".tmp")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, args.dst)
    for k, v in sorted(stats.items()):
        print(f"{k}: {v}")
    print(f"wrote {len(rows)} hospitals -> {args.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
