"""data/sources.csv, the list of what `hfal fetch` downloads (`hospital_id, url, label`), and its row labels.

Two kinds of row share the file:
  * landing-page rows (LANDING_LABEL), written by `hfal sources` from data/hospitals.csv: where discovery starts;
  * discovered rows (DISCOVERED_LABEL + " pdf|docx|html", optionally + BROWSER_SUFFIX), written by `hfal discover`.
Each writer replaces only its own rows and keeps the other's.

`hfal sources --set dev|eval|all` replaces every landing-page row with one row per URL in `landing_url` for the
hospitals of that set.

Evaluation honesty: eval hospitals must keep the golden sheet's link. If an eval hospital's url_source is
not the golden sheet, this step warns (its score would then reflect our curation, not the pipeline).
"""

from . import paths
from .files import read_csv, write_csv
from .hospitals import load_table

LANDING_LABEL = "HFA landing page"
DISCOVERED_LABEL = "discovered"
BROWSER_SUFFIX = " (browser)"   # on a discovered web page: fetch it with the headless browser (discover.py)
GOLDEN_SOURCE = "golden sheet (Sept 2025)"
FIELDS = ["hospital_id", "url", "label"]


def sources_path():
    return paths.DATA / "sources.csv"


def read_sources() -> list[dict]:
    """Every row of data/sources.csv; [] when the file does not exist yet."""
    f = sources_path()
    return read_csv(f) if f.exists() else []


def write_sources(rows: list[dict]) -> None:
    """Rewrite data/sources.csv with these rows (atomically: the old file or the whole new one)."""
    write_csv(sources_path(), rows, FIELDS, extrasaction="ignore", atomic=True)


def landing_urls(only: set[str] | None = None) -> dict[str, list[str]]:
    """hospital_id -> its landing-page URLs, from the landing-page rows of data/sources.csv."""
    out: dict[str, list[str]] = {}
    for r in read_sources():
        if r.get("label") == LANDING_LABEL and (only is None or r["hospital_id"] in only):
            out.setdefault(r["hospital_id"], []).append(r["url"].strip())
    return out


def landing_rows(table: list[dict], set_name: str, only: set[str] | None = None) -> tuple[list[dict], dict]:
    """The landing-page rows for the hospitals of a set, and counts about them."""
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
    """`hfal sources`: replace the landing-page rows for a set; keep every other row."""
    rows, stats = landing_rows(load_table(), set_name, only)
    kept = [r for r in read_sources() if r.get("label") != LANDING_LABEL]
    write_sources(kept + rows)
    for k, v in stats.items():
        print(f"{k}: {v}")
    if stats["eval_url_not_from_golden"]:
        print("WARNING: some eval hospitals have hand-edited landing URLs; eval results would reflect curation")
    print(f"kept {len(kept)} other rows; wrote {len(kept) + len(rows)} rows -> {sources_path()}")
