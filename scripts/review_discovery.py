"""Write a review sheet for discovery on the dev set, and summarize it once filled in.

    uv run python scripts/review_discovery.py              # writes data/review/discovery_review.csv
    uv run python scripts/review_discovery.py --force      # overwrite an existing sheet (loses answers!)
    uv run python scripts/review_discovery.py --summarize  # counts from a filled-in sheet

One row per document link discovery considered for a dev hospital (translations left out):
  status = "selected", or "not selected: <reason>" (low score, over the cap, names another hospital)

Fill in three columns (open the CSV in Excel; open `local_file` or `url` to read the document):
  relevant   Y / N / ?   selected rows: is this a right document FOR THIS HOSPITAL?
                         not-selected rows: should it have been selected? (Y = discovery missed it)
  doc_type   policy / summary / application / billing / other
  note       anything else (e.g. "outdated 2019 version", "covers all system hospitals")

Hospitals with no document text (PLAN.md "Deferred") are left out. Prints counts only.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from hfal import discover as d
from hfal import hospitals, paths
from hfal.files import EXCEL, read_csv, read_json, write_csv
from hfal.manifest import latest_manifest

OUT = paths.DATA / "review" / "discovery_review.csv"
FIELDS = ["hospital_id", "hospital_name", "system", "status", "kind", "link_text", "url", "found_on",
          "local_file", "first_line", "pages", "chars", "needs_ocr", "text_names_this_hospital",
          "text_names_other_hospitals", "score", "relevant", "doc_type", "note"]


def first_line(pages: list[str]) -> str:
    """The first line of the first two pages with at least three words (a title, usually)."""
    for line in "\n".join(pages[:2]).splitlines():
        line = " ".join(line.split())
        if len(line.split()) >= 3:
            return line[:140]
    return ""


def html_title(path: Path) -> str:
    soup = BeautifulSoup(path.read_bytes(), "html.parser")
    return " ".join(soup.title.get_text().split())[:140] if soup.title else ""


def text_names(text: str, nf: dict | None, table: dict) -> tuple[str, str]:
    """(Y/N: text names this hospital, names of other hospitals the text names): a review hint, not a verdict."""
    if not nf:
        return "", ""
    toks = set(re.findall(r"[a-z0-9]+", text.lower()))
    own = bool(nf["own"]["words"] & toks) or any(len(a) >= 3 and a in toks for a in nf["own"]["acronyms"])
    others = [k for k, o in nf["others"].items()
              if not k.startswith("system:") and ((o["words"] and o["words"] <= toks) or (o["unique"] & toks))]
    names = sorted(table[k]["name"] for k in others if k in table)
    return ("Y" if own else "N"), "; ".join(names[:3]) + (f" (+{len(names) - 3} more)" if len(names) > 3 else "")


def _candidate_row(h: dict, c: dict, item: dict | None, nf: dict | None, table: dict) -> dict:
    """One sheet row for a discovery candidate, with what we know of the downloaded file."""
    hid = h["hospital_id"]
    row = {"hospital_id": hid, "hospital_name": h["name"], "system": h["system"],
           "status": "selected" if c["selected"] else f"not selected: {c['reason']}",
           "kind": c["kind"], "link_text": c["anchor"][:120], "url": c["url"], "found_on": c.get("found_on", ""),
           "score": c["score"], "relevant": "", "doc_type": "", "note": ""}
    if item:
        local = paths.RAW / hid / "files" / f"{item['sha8']}.{item['ext']}"
        row["local_file"] = str(local.relative_to(paths.ROOT))
        text_file = paths.TEXT / hid / f"{item['sha8']}.json"
        if text_file.exists():
            t = read_json(text_file)
            row.update(pages=len(t["pages"]), chars=sum(len(p) for p in t["pages"]),
                       needs_ocr="Y" if t["needs_ocr"] else "")
            row["first_line"] = html_title(local) if item["ext"] == "html" else first_line(t["pages"])
            own, others = text_names(" ".join(t["pages"]), nf, table)
            row.update(text_names_this_hospital=own, text_names_other_hospitals=others)
    elif c["selected"]:
        row["note"] = "(not downloaded: see the manifest status)"
    return row


def build_rows() -> tuple[list[dict], Counter]:
    table = hospitals.by_id()
    stats = Counter()
    rows = []
    dev = sorted((h for h in table.values() if h.get("set") == "dev"), key=lambda h: int(h["hospital_id"]))
    for h in dev:
        hid = h["hospital_id"]
        disc = paths.DATA / "discovered" / f"{hid}.json"
        stored = {i["url"]: i for i in latest_manifest(hid)}
        has_docs = any(i["ext"] in d.DOC_KINDS for i in stored.values())
        if not disc.exists() or not has_docs:
            stats["dev_hospitals_skipped_no_document_text"] += 1
            continue
        stats["dev_hospitals_in_sheet"] += 1
        res = read_json(disc)
        nf = d.name_filter(hid, table)
        for c in res["candidates"]:
            if c["kind"] == "translation" or str(c.get("reason", "")).startswith("translation"):
                continue
            if c["kind"] == "html" and not c["selected"]:
                continue                       # unselected HTML pages are mostly navigation; not worth reviewing
            rows.append(_candidate_row(h, c, stored.get(c["url"]), nf, table))
            stats["rows_selected" if c["selected"] else "rows_not_selected"] += 1
    return rows, stats


def summarize(path: Path) -> None:
    rows = read_csv(path)       # the sheet is written (and Excel saves it) with a BOM

    def ans(r):
        return r["relevant"].strip().upper()[:1]

    sel = [r for r in rows if r["status"] == "selected"]
    nsel = [r for r in rows if r["status"] != "selected"]
    c_sel, c_nsel = Counter(ans(r) or "blank" for r in sel), Counter(ans(r) or "blank" for r in nsel)
    print(f"selected documents:      {dict(c_sel)}")
    print(f"not-selected documents:  {dict(c_nsel)}   (Y = discovery missed it)")
    judged = c_sel["Y"] + c_sel["N"]
    if judged:
        print(f"precision (selected that are right): {c_sel['Y']}/{judged} = {c_sel['Y'] / judged:.0%}")
    found = c_sel["Y"]
    if found + c_nsel["Y"]:
        print(f"share of right documents discovery found: {found}/{found + c_nsel['Y']} = {found / (found + c_nsel['Y']):.0%}")
    by_h = {}
    for r in sel:
        by_h.setdefault(r["hospital_id"], []).append(ans(r))
    print(f"hospitals with at least one wrong selected document: {sum('N' in v for v in by_h.values())} of {len(by_h)}")
    print("doc types marked:", dict(Counter(r["doc_type"].strip().lower() or "blank" for r in sel if ans(r) == "Y")))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--force", action="store_true", help="overwrite an existing sheet (its answers are lost)")
    p.add_argument("--summarize", action="store_true", help="print counts from a filled-in sheet")
    args = p.parse_args()

    if args.summarize:
        summarize(args.out)
        return 0
    if args.out.exists() and not args.force:
        print(f"{args.out} exists and may hold your answers; use --force to overwrite or --out for a new file")
        return 1
    rows, stats = build_rows()
    write_csv(args.out, rows, FIELDS, encoding=EXCEL)      # utf-8-sig: Excel shows accents right
    for k, v in sorted(stats.items()):
        print(f"{k}: {v}")
    print(f"wrote {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
