"""Multi-label document-type tagging. Keyword rules first; flag what they miss.

A single PDF often holds several things (policy + summary + application), so a
document can carry more than one type.
"""

import json
import re

from . import paths

RULES: dict[str, list[str]] = {
    "fap_policy": [r"financial assistance polic", r"charity care polic", r"financial aid polic"],
    "plain_language_summary": [r"plain[- ]language", r"summary of (the )?(financial assistance|charity care)", r"\bfap summary"],
    "application_form": [r"application (form )?for (financial assistance|charity care)", r"(financial assistance|charity care) application"],
    "billing_collections_policy": [r"billing and collection", r"collections? polic", r"debt collection"],
    "provider_list": [r"provider list", r"list of providers", r"providers (covered|not covered)"],
    "signage_notice": [r"\bsignage\b", r"notice of (the )?availab"],
}


def tag_document(url: str, label: str, first_page: str) -> dict:
    haystack = f"{url} {label} {first_page[:1500]}".lower().replace("_", " ").replace("-", " ")
    types = [t for t, pats in RULES.items() if any(re.search(p, haystack) for p in pats)]
    if not types:
        return {"types": ["other"], "needs_review": True}
    return {"types": types, "needs_review": False}


def tag_all(only: set[str] | None = None) -> None:
    if not paths.TEXT.exists():
        return
    for hdir in sorted(p for p in paths.TEXT.iterdir() if p.is_dir()):
        hid = hdir.name
        if only and hid not in only:
            continue
        tags = {}
        for f in sorted(hdir.glob("*.json")):
            doc = json.loads(f.read_text(encoding="utf-8"))
            first = doc["pages"][0] if doc["pages"] else ""
            tags[doc["sha8"]] = tag_document(doc["source_url"], doc.get("label", ""), first)
        paths.TAGS.mkdir(parents=True, exist_ok=True)
        (paths.TAGS / f"{hid}.json").write_text(json.dumps(tags, indent=2), encoding="utf-8")
        print(f"{hid}  tagged {len(tags)} docs")
