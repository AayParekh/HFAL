"""The hospital table we own: data/hospitals.csv (seeded by scripts/seed_hospitals.py; CLAUDE.md "Decisions").

Columns: hospital_id (the PFI, a string), name, address, city, zip, system, set (dev | eval), landing_url (one or
more URLs separated by spaces), url_source, verified_at, note. The file is git-ignored (identity rows come from
CSSNY's sheet), so every reader here copes with it being absent in one of two ways:
  * load_table() stops with a message saying how to build it (commands that cannot do anything without it);
  * by_id() / sets() / dev_ids() return an empty table (commands that only use it for names or for the dev/eval split
    and can carry on without).
"""

from . import paths
from .files import read_csv

FILE_NAME = "hospitals.csv"


def table_path():
    return paths.DATA / FILE_NAME


def load_table() -> list[dict]:
    """Every row of the table. Stops with a hint when the file is missing or predates the landing_url column."""
    f = table_path()
    if not f.exists():
        raise SystemExit(f"{f} not found; run: uv run python scripts/seed_hospitals.py")
    rows = read_csv(f)
    if rows and "landing_url" not in rows[0]:
        raise SystemExit(f"{f} has no landing_url column; run: uv run python scripts/seed_hospitals.py")
    return rows


def by_id() -> dict[str, dict]:
    """hospital_id -> row, or {} when the table is not there (name filters and reports then go without names)."""
    f = table_path()
    return {r["hospital_id"]: r for r in read_csv(f)} if f.exists() else {}


def sets() -> dict[str, str]:
    """hospital_id -> 'dev' / 'eval' (or '' when unset); empty when the table is not there."""
    return {hid: r.get("set", "") for hid, r in by_id().items()}


def dev_ids() -> set[str]:
    """The dev hospitals: the only ones whose disagreements with the golden labels may be read (CLAUDE.md)."""
    return {hid for hid, s in sets().items() if s == "dev"}
