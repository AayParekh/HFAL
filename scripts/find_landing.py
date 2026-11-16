"""EXPERIMENT (Nov 14, owner): find a hospital's financial-assistance page without CSSNY's sheet.

    uv run python scripts/find_landing.py --validate        # dev hospitals that HAVE a link: does it find the same page?
    uv run python scripts/find_landing.py --no-link         # hospitals with no landing link: what does it find?
    add --crawl to --validate to also compare the documents discovery selects from the found page

38 hospitals have no landing link because CSSNY's sheet has text, not a URL, in HFA Link. The state's own facility data
(health.data.ny.gov, NYS Health Profiles) lists names, addresses and phones but no website, so the starting page must
come from a web search. One fixed search per hospital, fixed rules to accept a result, no model, no golden labels:

  query   "{name} {city} NY financial assistance"   (DuckDuckGo's plain HTML results, our honest user agent)
  accept  the first of the top 10 results that
            - is not on a directory or bill-help site (AGGREGATORS below),
            - is not a PDF or Word file (the starting page is a web page; discovery finds the documents),
            - has a strong financial-assistance keyword in its title or address (discover.score >= 3), and
            - names this hospital or its health system in its WEB ADDRESS (a word of the name, or its acronym, in
              the host name), and names no other hospital in our table (discover's name filter). Directories put the
              name in the page title, not in their own address, so a title match alone is not enough (dev
              validation, Nov 14: title matches let 30 bill-help directory pages through).

Searches are cached in data/found_landing/search/{hospital_id}.json (git-ignored), so a re-run gives the same answer
and searches nothing again. Results go to data/found_landing/found.csv (git-ignored). It NEVER edits
data/hospitals.csv: adding a found page there (url_source "web search, Nov 2026") is a separate decision, and would
change how results are framed ("given a known starting page" no longer holds for those hospitals).

Validation uses dev hospitals only (CLAUDE.md, Evaluation honesty). It prints counts only.
"""

import argparse
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

from hfal import discover, hospitals, paths
from hfal.fetch import make_client
from hfal.files import read_json, write_csv, write_json

SEARCH_URL = "https://html.duckduckgo.com/html/?q={q}"
TOP_N = 10
DELAY_SECONDS = 6.0     # at 3 s the search answered 11 of 90 queries with 202 ("slow down")
OUT = paths.DATA / "found_landing"
# Directory, review, bill-help, news and social sites: they name the hospital and "financial assistance" but are not
# the hospital's own page.
AGGREGATORS = {
    "billstand.com", "cobijohealth.org", "dollarfor.org", "wikipedia.org", "yelp.com", "healthgrades.com",
    "usnews.com", "facebook.com", "linkedin.com", "indeed.com", "glassdoor.com", "mapquest.com", "npiregistry.cms.hhs.gov",
    "cms.gov", "medicare.gov", "ny.gov", "propublica.org", "guidestar.org", "causeiq.com", "turquoise.health",
    "zocdoc.com", "vitals.com", "webmd.com", "castleconnolly.com", "leapfroggroup.org", "newsweek.com",
    "beckershospitalreview.com", "youtube.com", "instagram.com", "x.com", "twitter.com", "bbb.org", "yellowpages.com",
    "manta.com", "communitybenefitinsight.org", "hospitalpricing.com", "medicaid.gov", "healthcare.gov",
    "nerdwallet.com", "goodrx.com", "patientadvocate.org", "lowninstitute.org", "hospitalsafetygrade.org",
    "nytimes.com", "reddit.com", "bing.com", "duckduckgo.com", "google.com", "irs.gov", "hhs.gov", "nih.gov",
    "medicalbillingadvocates.com", "billfairly.com", "fairvisithealth.com", "unduemedicaldebt.org", "cssny.org", "communityservicesociety.org",
}
HOST_SUFFIXES = re.compile(r"(health|hospital|hosp|medical|med|medicalcenter|healthcare|healthsystem|hs|mc|org)$")


def registered(host: str) -> str:
    return ".".join(host.lower().split(":")[0].split(".")[-2:])


def search(client, hid: str, query: str) -> dict:
    """Top results for query, cached per hospital (the first search is kept for good)."""
    f = OUT / "search" / f"{hid}.json"
    if f.exists():
        cached = read_json(f)
        if cached.get("query") == query and cached.get("status") == 200:
            return cached
    time.sleep(DELAY_SECONDS)
    try:
        r = client.get(SEARCH_URL.format(q=quote_plus(query)))
        status, html = r.status_code, r.text
    except Exception as e:  # recorded, never fatal
        status, html = f"error: {type(e).__name__}", ""
    results = []
    for a in BeautifulSoup(html, "html.parser").select("a.result__a")[:TOP_N]:
        href = a.get("href", "")
        target = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        results.append({"url": target, "title": a.get_text(" ", strip=True)})
    rec = {"hospital_id": hid, "query": query, "status": status, "results": results,
           "searched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "blocked": bool(re.search(r"anomaly|captcha", html, re.I)) and not results}
    write_json(f, rec, ensure_ascii=False)
    return rec


def names_hospital(me: dict, nf: dict | None, url: str, title: str) -> tuple[bool, list[str]]:
    """(names this hospital or its system?, other hospitals it names) from the web address and title."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    labels = re.split(r"[.-]", host)[:-1]                 # "auburnhospital.org" -> ["auburnhospital"]
    own_words = (discover.name_words(me["name"]) | discover.name_words(me.get("system", ""))) - discover.GENERIC_NAME_WORDS
    acronyms = {a for a in (discover.acronym(me["name"]), discover.acronym(me.get("system", ""))) if a}
    in_host = any(w in lab for w in own_words if len(w) >= 4 for lab in labels) or \
        any(HOST_SUFFIXES.sub("", lab) in acronyms or lab in acronyms for lab in labels)
    _, others = discover._names(nf, title, url)
    return in_host, others


def choose(me: dict, nf: dict | None, results: list[dict]) -> tuple[dict | None, list[str]]:
    """The first acceptable result, and why each earlier one was passed over."""
    why = []
    for i, r in enumerate(results, 1):
        url, title = r["url"], r["title"]
        p = urlparse(url)
        host = p.netloc.lower()
        if p.scheme not in ("http", "https"):
            why.append(f"{i}: not a web address")
        elif registered(host) in AGGREGATORS or any(host.endswith(a) for a in AGGREGATORS):
            why.append(f"{i}: directory or bill-help site")
        elif discover.is_doc_url(url):
            why.append(f"{i}: a document, not a page")
        elif discover.score(title, url) < discover.FOLLOW_MIN_SCORE:
            why.append(f"{i}: no financial-assistance keyword")
        else:
            own, others = names_hospital(me, nf, url, title)
            if others:
                why.append(f"{i}: names another hospital")
            elif not own:
                why.append(f"{i}: web address does not name this hospital or its system")
            else:
                return {**r, "rank": i}, why
    return None, why


def norm(url: str) -> tuple[str, str]:
    p = urlparse(url.strip())
    return p.netloc.lower().removeprefix("www."), p.path.rstrip("/").lower()


def compare(found: str, known: str) -> str:
    (fh, fp), (kh, kp) = norm(found), norm(known)
    if (fh, fp) == (kh, kp):
        return "same page"
    if registered(fh) == registered(kh):
        return "same site, other page"
    return "other site"


def selected_docs(res: dict) -> set[str]:
    return {c["url"] for c in res["candidates"] if c["selected"] and c["kind"] in discover.DOC_KINDS}


def crawl_docs(client, landing: str, hid: str, table: dict) -> set[str]:
    """PDF / Word documents discovery would select starting from landing (plain HTTP, discovery's rules)."""
    def get(u):
        time.sleep(paths.settings()["fetch"]["delay_seconds"])
        try:
            r = client.get(u)
            return r.status_code, r.headers.get("content-type", ""), r.content
        except Exception as e:
            return f"error: {type(e).__name__}", "", b""
    return selected_docs(discover.select(discover.crawl(landing, get), landing, discover.name_filter(hid, table)))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true", help="dev hospitals with a link: compare")
    mode.add_argument("--no-link", action="store_true", help="hospitals without a link: find one")
    p.add_argument("--crawl", action="store_true", help="with --validate: compare the documents discovery selects")
    args = p.parse_args()

    table = hospitals.by_id()
    if args.validate:
        todo = [h for h in table.values() if h.get("set") == "dev" and h.get("landing_url", "").strip()]
    else:
        todo = [h for h in table.values() if not h.get("landing_url", "").strip()]
    rows, outcome = [], Counter()
    with make_client(30) as client:
        for h in sorted(todo, key=lambda x: x["hospital_id"]):
            hid = h["hospital_id"]
            query = f"{h['name']} {h.get('city', '')} NY financial assistance".replace("  ", " ")
            rec = search(client, hid, query)
            if rec["status"] != 200:
                outcome["search failed"] += 1
                rows.append({"hospital_id": hid, "set": h.get("set", ""), "query": query, "result": "search failed"})
                continue
            got, why = choose(h, discover.name_filter(hid, table), rec["results"])
            row = {"hospital_id": hid, "set": h.get("set", ""), "query": query,
                   "found_url": got["url"] if got else "", "found_title": got["title"] if got else "",
                   "rank": got["rank"] if got else "", "passed_over": "; ".join(why),
                   "searched_at": rec["searched_at"]}
            if args.validate:
                row["result"] = compare(got["url"], h["landing_url"]) if got else "nothing accepted"
                if args.crawl and got and row["result"] != "same page":
                    found_docs = crawl_docs(client, got["url"], hid, table)
                    disc = paths.DATA / "discovered" / f"{hid}.json"
                    known = selected_docs(read_json(disc)) if disc.exists() else set()
                    row["same_documents"] = ("all" if known and found_docs >= known else
                                             "some" if found_docs & known else "none")
                    outcome[(row["result"], "documents: " + row["same_documents"])] += 1
                else:
                    outcome[row["result"]] += 1
            else:
                row["result"] = "found" if got else "nothing accepted"
                outcome[(h.get("set", ""), row["result"])] += 1
            rows.append(row)
            print(f"{len(rows)}/{len(todo)}", file=sys.stderr, end="\r")

    name = "validate.csv" if args.validate else "found.csv"
    fields = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
    write_csv(OUT / name, rows, fields)
    print(f"\n{'validation (dev hospitals with a link)' if args.validate else 'hospitals without a link'}: {len(rows)}")
    for k, v in sorted(outcome.items(), key=lambda kv: -kv[1]):
        print(f"  {v:3d}  {k}")
    passed = Counter(w.split(": ", 1)[1] for r in rows for w in (r.get("passed_over") or "").split("; ") if w)
    print("results passed over, by reason:", dict(passed.most_common()))
    print(f"-> {OUT / name} (git-ignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
