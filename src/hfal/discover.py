"""Find each hospital's financial-assistance documents, starting from its landing page.

Rules and the reasons for each keyword: docs/discovery.md (keep it in sync with this file).

Crawl: start from the landing page saved by `hfal fetch` (re-requesting it can trip bot protection), then
follow same-site links whose URL or link text has a strong financial-assistance keyword, up to MAX_DEPTH
clicks and MAX_PAGES pages per hospital. Collect every PDF link seen (any host: PDFs are often on a CDN).
Strongly-keyworded links to other hosts are opened once, without crawling them, because document hosts
(e.g. widen.net) serve PDFs from links that do not end in .pdf.

Select, by fixed rules (no model, no golden labels):
  - Translations are not downloaded. A PDF whose link text or file name names a language other than
    English is recorded (its language goes in `languages_seen`) but not selected.
  - Remaining PDFs are scored by keywords; score >= PDF_MIN_SCORE is selected, best MAX_DOCS kept.
  - HTML pages visited after the landing page with a strong keyword are selected too (summaries are
    often written on the page itself).
  - Health systems: a candidate whose link text or URL path names another hospital or health system
    (data/hospitals.csv), and not this one, is dropped. Candidates naming this hospital rank higher.
    Another hospital matches by all of its distinctive words (no "hospital", "medical", city or system
    words), by any distinctive word of 5+ letters that no other hospital has ("hazel"), or by its acronym
    as a whole word ("smh" = Spruce Memorial Hospital). Another system also matches by the acronym of the
    part of its name it does not share with this hospital's system ("flh" = ... Finger Lakes Health).

Headless browser (Nov 14): when plain HTTP finds no PDF or Word document, the crawl is run again with every page
rendered in Chromium (browser.py) and its result is used if it finds documents, or finds anything where plain HTTP
found nothing. Pages it selects are labelled so that `hfal fetch` renders them too.

Output: data/discovered/{hospital_id}.json (every candidate with its score and why it was or was not
selected) and rows labelled "discovered" in data/sources.csv. The same pages always give the same
result, so the monthly check can diff runs.
"""

import re
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from . import hospitals, paths
from .files import write_json
from .manifest import latest_manifest
from .sources import BROWSER_SUFFIX, DISCOVERED_LABEL, landing_urls, read_sources, write_sources

MAX_DEPTH = 2
MAX_PAGES = 10         # pages fetched per hospital, landing page included
MAX_DOCS = 12          # PDFs selected per hospital
MAX_PAGES_KEPT = 3     # extra HTML pages selected per hospital
FOLLOW_MIN_SCORE = 3   # a link must have a strong keyword to be followed
PDF_MIN_SCORE = 3
DOC_KINDS = ("pdf", "docx")

STRONG = [r"financial[ -]?(assistance|aid)", r"charity[ -]?care", r"sliding[ -]?(fee|scale)",
          r"uniform[ -]?(financial|application)", r"hospital[ -]?financial[ -]?assistance", r"\bhfa\b", r"\bfap\b",
          r"hfal\b"]
MEDIUM = [r"application", r"\bpolic(y|ies)\b", r"summary", r"plain[ -]?language", r"brochure", r"\bfa\b",
          r"billing[ -]?(and|&)?[ -]?collection", r"uninsured", r"self[ -]?pay", r"discount"]
WEAK = [r"\bfaq\b", r"frequently asked", r"pay[ -]?(my|your)?[ -]?bill", r"billing", r"patient[ -]?financial"]
NEGATIVE = [r"insurance plans?", r"participating[ -]?plan", r"surprise", r"price[ -]?transparency",
            r"standard[ -]?charges", r"chargemaster", r"estimate", r"privacy", r"visitor", r"careers?\b",
            r"\bjobs?\b", r"annual[ -]?report", r"covid", r"menu", r"newsletter"]

LANGUAGES = {
    "english": "english", "spanish": "spanish", "espanol": "spanish", "español": "spanish",
    "arabic": "arabic", "العربية": "arabic", "االعربية": "arabic", "chinese": "chinese", "中文": "chinese",
    "simplified chinese": "chinese", "traditional chinese": "chinese", "mandarin": "chinese",
    "cantonese": "chinese", "russian": "russian", "русский": "russian", "bengali": "bengali", "বাংলা": "bengali",
    "haitian creole": "haitian creole", "kreyol": "haitian creole", "kreyòl": "haitian creole",
    "kreyòl ayisyen": "haitian creole", "creole": "haitian creole", "french": "french", "français": "french",
    "korean": "korean", "한국어": "korean", "polish": "polish", "polski": "polish", "italian": "italian",
    "italiano": "italian", "yiddish": "yiddish", "ייִדיש": "yiddish", "urdu": "urdu", "اردو": "urdu",
    "hindi": "hindi", "हिंदी": "hindi", "greek": "greek", "ελληνικά": "greek", "albanian": "albanian",
    "shqip": "albanian", "portuguese": "portuguese", "brazilian portuguese": "portuguese",
    "português": "portuguese", "ukrainian": "ukrainian", "українська": "ukrainian", "vietnamese": "vietnamese",
    "tiếng việt": "vietnamese", "nepali": "nepali", "swahili": "swahili", "burmese": "burmese",
    "farsi": "farsi", "persian": "farsi", "tagalog": "tagalog", "japanese": "japanese", "日本語": "japanese",
    "german": "german", "deutsch": "german", "hebrew": "hebrew", "punjabi": "punjabi", "tibetan": "tibetan",
    "uzbek": "uzbek", "somali": "somali", "dari": "dari", "pashto": "pashto", "turkish": "turkish",
    "hmong": "hmong", "fulani": "fulani", "wolof": "wolof", "georgian": "georgian", "armenian": "armenian",
    "karen": "karen", "tigrinya": "tigrinya", "amharic": "amharic", "bosnian": "bosnian", "serbian": "serbian",
    "croatian": "croatian", "romanian": "romanian", "mongolian": "mongolian", "khmer": "khmer", "lao": "lao",
    "thai": "thai", "malay": "malay", "indonesian": "indonesian", "yoruba": "yoruba", "igbo": "igbo",
    "twi": "twi", "gujarati": "gujarati", "tamil": "tamil", "telugu": "telugu", "marathi": "marathi",
    "malayalam": "malayalam", "kinyarwanda": "kinyarwanda", "kirundi": "kirundi", "dinka": "dinka",
    "marshallese": "marshallese", "chuukese": "chuukese", "ilocano": "ilocano", "lithuanian": "lithuanian",
    "hungarian": "hungarian", "czech": "czech", "slovak": "slovak", "dutch": "dutch", "swedish": "swedish",
}
# Three-letter language codes seen in file names ("..._eng_us-spa_es.pdf"). Codes that are also English
# words or common abbreviations (pol, per, pan, ger, may, ita, fre, fas = "financial assistance summary")
# are left out on purpose.
LANGUAGE_CODES = {
    "eng": "english", "spa": "spanish", "ben": "bengali", "rus": "russian", "ara": "arabic", "hat": "haitian creole",
    "yid": "yiddish", "zhs": "chinese", "zht": "chinese", "zho": "chinese", "chi": "chinese", "kor": "korean",
    "urd": "urdu", "hin": "hindi", "ell": "greek", "sqi": "albanian", "alb": "albanian", "por": "portuguese",
    "ukr": "ukrainian", "vie": "vietnamese", "nep": "nepali", "swa": "swahili", "mya": "burmese",
    "tgl": "tagalog", "jpn": "japanese", "deu": "german", "heb": "hebrew", "fra": "french",
}
# Link text written in a non-Latin script names its language even when it is not a language name.
SCRIPTS = [  # (first, last code point, label)
    (0x0980, 0x09FF, "bengali"), (0x0400, 0x04FF, "cyrillic script"), (0x0600, 0x06FF, "arabic script"),
    (0x0590, 0x05FF, "hebrew script"), (0x4E00, 0x9FFF, "chinese"), (0xAC00, 0xD7AF, "korean"),
    (0x0900, 0x097F, "devanagari script"), (0x0370, 0x03FF, "greek"), (0x1000, 0x109F, "burmese"),
    (0x3040, 0x30FF, "japanese"), (0x0A00, 0x0A7F, "punjabi"), (0x0E00, 0x0E7F, "thai"),
]
_LANG_TOKEN = re.compile(r"(?:^|[-_ .(/])(" + "|".join(
    sorted((re.escape(k) for k in LANGUAGES if k.isascii()), key=len, reverse=True)) + r")(?=$|[-_ .)/])")


GENERIC_NAME_WORDS = {
    "hospital", "hospitals", "medical", "center", "centers", "centre", "health", "healthcare", "memorial",
    "the", "and", "inc", "regional", "community", "general", "saint", "university", "system", "campus",
    "care", "services", "network", "county", "new", "york", "division", "facility", "clinic", "clinics",
    "rehabilitation", "nursing", "home", "for", "association", "corporation", "corp", "llc", "district",
    "hosp", "ctr", "med", "aka", "west", "east", "north", "south", "upper", "lower", "central", "main",
    # ordinary words that appear in some hospital names but also in unrelated URLs and link text
    "heart", "department", "cancer", "children", "childrens", "women", "womens", "infirmary", "behavioral",
    "psychiatric", "surgery", "surgical", "specialty", "special", "eye", "ear", "institute", "foundation",
    "pavilion", "emergency", "family", "valley", "lake", "lakes", "river", "park", "island", "city", "town",
    "village", "mount", "hill", "hills", "view", "good", "samaritan", "mercy", "faith", "hope", "grace",
    "unity", "union", "united", "national", "state", "public", "private", "orthopedic", "orthopaedic",
    "cardiac", "kidney", "dental", "veterans", "affairs", "sciences", "science", "research", "teaching",
    "physicians", "providers", "partners", "associates", "group", "affiliate", "affiliated", "member",
}
OTHER_ACRONYM_MIN_LEN = 3   # 2-letter acronyms ("us", "es") collide with locale codes in URLs...
LOCALE_CODES = {"en", "es", "us", "fr", "zh", "ru", "ar", "ht", "ko", "pl", "it", "bn", "ur", "yi", "hi", "el",
                "sq", "pt", "uk", "vi", "ne", "sw", "my", "fa", "tl", "ja", "de", "he", "pa", "so", "tr", "cn", "tw",
                "ch", "sp", "kr"}
# ...so a 2-letter acronym only counts as the last part of a file name ("policy-hh.docx"), never a locale.
UNIQUE_WORD_MIN_LEN = 5
OWN_NAME_BONUS = 3


# ---------------------------------------------------------------------------------------------------------------
# Hospital and health-system names (the name filter)

def name_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", text.lower().replace("'", "")))


def distinctive(name: str, city: str = "", system: str = "") -> set[str]:
    """Words that identify a hospital among its system's members, e.g. 'Alder Memorial Hospital' -> {'alder'}."""
    return name_words(name) - GENERIC_NAME_WORDS - name_words(city) - name_words(system)


ACRONYM_STOP = {"fap", "hfa", "faq", "pdf", "doc", "eng", "spa", "app", "the", "and", "for"}


def acronym(name: str) -> str:
    """First letters of the words: 'Spruce Memorial Hospital' -> 'smh'. '' if under 2 letters or ambiguous."""
    a = "".join(w[0] for w in re.findall(r"[a-z]+", name.lower().replace("'", "")) if w not in ("of", "the", "and"))
    return a if len(a) >= 2 and a not in ACRONYM_STOP else ""


def name_filter(hid: str, table: dict[str, dict]) -> dict | None:
    """Names to look for in candidate links.

    {'own': {'words', 'acronyms'}, 'others': {key: {'words', 'acronym'}}} where others are every other
    hospital (key = hospital_id) and every other health system (key = 'system: <name>'). None if hid unknown.
    """
    me = table.get(hid)
    if not me:
        return None
    my_system = me.get("system", "")
    # Own words keep the city ("Westfield Memorial" in Westfield): a false match here only ranks a doc higher.
    own_words = name_words(me["name"]) - GENERIC_NAME_WORDS - name_words(my_system)
    own_acr = {a for a in (acronym(me["name"]), acronym(my_system)) if a}
    word_count: dict[str, int] = {}
    for h in table.values():
        for w in distinctive(h["name"], h.get("city", ""), h.get("system", "")):
            word_count[w] = word_count.get(w, 0) + 1
    others = {}

    def add(key, words, acronyms):
        words = words - own_words
        unique = {w for w in words if word_count.get(w) == 1 and len(w) >= UNIQUE_WORD_MIN_LEN}
        short = {a for a in acronyms if len(a) == 2 and a not in LOCALE_CODES and a not in own_acr}
        acronyms = {a for a in acronyms if len(a) >= OTHER_ACRONYM_MIN_LEN and a not in own_acr}
        if words or acronyms or short:
            others[key] = {"words": words, "unique": unique, "acronyms": acronyms, "suffix_acronyms": short}

    for oid, h in table.items():
        if oid != hid:
            add(oid, distinctive(h["name"], h.get("city", ""), h.get("system", "")), {acronym(h["name"])})
    shared = name_words(my_system)
    for system in sorted({h.get("system", "") for h in table.values()} - {my_system, ""}):
        tail = " ".join(w for w in re.findall(r"[A-Za-z']+", system) if w.lower().replace("'", "") not in shared)
        add(f"system: {system}", distinctive(tail) or distinctive(system), {acronym(system), acronym(tail)})
    return {"own": {"words": own_words, "acronyms": own_acr}, "others": others}


def _names(nf: dict | None, anchor: str, url: str) -> tuple[bool, list[str]]:
    """(names this hospital?, ids of other same-system hospitals it names)."""
    if not nf:
        return False, []
    path = urlparse(url).path
    tokens = set(re.findall(r"[a-z0-9]+", _norm(f"{anchor} {path}").replace("'", "")))
    stem = path.rstrip("/").rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    last = re.split(r"[-_ .]+", stem)[-1] if stem else ""
    own = bool(nf["own"]["words"] & tokens) or bool(nf["own"]["acronyms"] & tokens)
    others = sorted(k for k, o in nf["others"].items()
                    if (o["words"] and o["words"] <= tokens) or (o["unique"] & tokens) or (o["acronyms"] & tokens)
                    or last in o["suffix_acronyms"])
    return own, others


# ---------------------------------------------------------------------------------------------------------------
# Scoring a link and reading its language

def _norm(text: str) -> str:
    return re.sub(r"(%20|[-_+/.])+", " ", text.lower())


def score(anchor: str, url: str) -> int:
    """Keyword score of a link. Higher = more likely a financial-assistance document.

    Positive keywords look at the link text and the whole URL path; negative keywords only at the link text
    and the file name, so a folder like /patients-visitors/ does not sink a policy PDF stored inside it.
    """
    path = urlparse(url).path
    hay = _norm(f"{anchor} {path}")
    tail = _norm(f"{anchor} {path.rstrip('/').rsplit('/', 1)[-1]}")
    s = 3 * sum(bool(re.search(p, hay)) for p in STRONG)
    s += 2 * sum(bool(re.search(p, hay)) for p in MEDIUM)
    s += 1 * sum(bool(re.search(p, hay)) for p in WEAK)
    s -= 5 * sum(bool(re.search(p, tail)) for p in NEGATIVE)
    return s


def language(anchor: str, url: str) -> str | None:
    """Language a link is labelled with (link text first, then file name), or None."""
    a = re.sub(r"\s*\(.*?\)\s*", " ", anchor).strip().lower()
    if a in LANGUAGES:
        return LANGUAGES[a]
    letters = [ch for ch in anchor if ch.isalpha()]
    if letters:
        for lo, hi, label in SCRIPTS:
            if sum(lo <= ord(ch) <= hi for ch in letters) / len(letters) > 0.5:
                return label
    name = urlparse(url).path.lower().rsplit("/", 1)[-1].replace("%20", " ")
    codes = [LANGUAGE_CODES[t] for t in re.split(r"[-_ .()]+", name) if t in LANGUAGE_CODES]
    non_english = [c for c in codes if c != "english"]
    if non_english:                       # "..._eng_us-spa_es.pdf" is the Spanish version of an English doc
        return non_english[-1]
    m = _LANG_TOKEN.search(name)
    if m:
        return LANGUAGES[m.group(1)]
    for part in re.findall(r"\(([^)]*)\)", anchor.lower()):   # "Application (Spanish)": last resort
        if part.strip() in LANGUAGES:
            return LANGUAGES[part.strip()]
    return "english" if codes else None


# ---------------------------------------------------------------------------------------------------------------
# URLs and pages

def site(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return ".".join(host.split(".")[-2:])


DOC_EXTENSIONS = (".pdf", ".docx")


def is_doc_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(DOC_EXTENSIONS)


def doc_kind(url: str, ctype: str, body: bytes = b"") -> str | None:
    """'pdf' or 'docx' if the response (or URL) is a document we can extract, else None."""
    ct = ctype.lower()
    path = urlparse(url).path.lower()
    if "pdf" in ct or body[:5] == b"%PDF-" or (not ct and path.endswith(".pdf")):
        return "pdf"
    if "wordprocessingml" in ct or (not ct and path.endswith(".docx")):
        return "docx"
    return None


def page_links(html: bytes | str, base_url: str) -> list[tuple[str, str]]:
    """(absolute url without fragment, link text) for every http(s) link, in page order, de-duplicated."""
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base_url, a["href"].strip()))[0]
        if urlparse(url).scheme not in ("http", "https"):
            continue
        text = a.get_text(" ", strip=True) or a.get("title", "") or a.get("aria-label", "")
        key = (url, text)
        if key not in seen:
            seen.add(key)
            out.append((url, text))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Crawl and select (pure given the responses)

# get(url) -> (status, content_type, body_bytes), or (status, "", b"") on failure
Getter = Callable[[str], tuple]


def crawl(landing: str, get: Getter) -> dict:
    """Returns {"pages": [...], "candidates": [...]} before selection. Deterministic for fixed responses."""
    home = site(landing)
    queue = [(0, -99, landing)]               # (depth, -score, url): best links first, breadth-first
    queued = {landing}
    pages, cands = [], {}
    while queue and len(pages) < MAX_PAGES:
        queue.sort()
        depth, neg, url = queue.pop(0)
        status, ctype, body = get(url)
        pages.append({"url": url, "depth": depth, "status": status})
        if status != 200:
            continue
        kind = doc_kind(url, ctype, body)
        if kind:                              # a link without .pdf/.docx that turned out to be a document
            cands.setdefault(url, {"url": url, "anchor": "", "found_on": "", "depth": depth})["kind"] = kind
            continue
        if site(url) != home:                 # off-site page: looked at, never crawled or selected
            cands.pop(url, None)
            continue
        if depth > 0:
            cands.setdefault(url, {"url": url, "kind": "html", "anchor": "", "found_on": "", "depth": depth})
        for link, text in page_links(body, url):
            if is_doc_url(link):
                kind = "docx" if urlparse(link).path.lower().endswith(".docx") else "pdf"
                c = cands.setdefault(link, {"url": link, "kind": kind, "anchor": text, "found_on": url, "depth": depth + 1})
                if not c["anchor"] and text:
                    c["anchor"] = text
            elif language(text, link) not in (None, "english"):
                # A translation behind an extensionless link: record its language, do not spend budget on it.
                cands.setdefault(link, {"url": link, "kind": "translation", "anchor": text, "found_on": url, "depth": depth + 1})
            elif depth < MAX_DEPTH and link not in queued:
                s = score(text, link)
                if s >= FOLLOW_MIN_SCORE:
                    queued.add(link)
                    queue.append((depth + 1, -s, link))
                    if link not in cands:
                        cands[link] = {"url": link, "kind": "html", "anchor": text, "found_on": url, "depth": depth + 1}
    fetched = {p["url"] for p in pages}
    # Followable HTML links we never got to are not candidates (nothing was read from them).
    return {"pages": pages, "candidates": [c for c in cands.values() if c["kind"] != "html" or c["url"] in fetched]}


def crawl_all(landings: list[str], get: Getter) -> dict:
    """crawl() from each landing page of a hospital (a few have more than one), pages and candidates pooled."""
    merged = {"pages": [], "candidates": []}
    for landing in landings:
        c = crawl(landing, get)
        merged["pages"] += c["pages"]
        merged["candidates"] += c["candidates"]
    return merged


def _other_hospital_reason(c: dict) -> str:
    return f"names another hospital ({', '.join(c['names_other_hospital'])})"


def select(crawled: dict, landing: str, nf: dict | None = None) -> dict:
    """Apply the fixed selection rules. Adds score/language/selected/reason to every candidate.

    nf: name filter from name_filter(); None disables the health-system rule.
    """
    langs = set()
    rows = []
    for c in crawled["candidates"]:
        c = {**c, "score": score(c["anchor"], c["url"]), "language": language(c["anchor"], c["url"])}
        own, others = _names(nf, c["anchor"], c["url"])
        c["rank"] = c["score"] + (OWN_NAME_BONUS if own else 0)   # bonus orders documents, never qualifies one
        c["names_other_hospital"] = others if not own else []
        if c["language"]:
            langs.add(c["language"])
        rows.append(c)

    pdfs = [c for c in rows if c["kind"] in (*DOC_KINDS, "translation")]
    pages = [c for c in rows if c["kind"] == "html" and c["url"] != landing]
    for c in pdfs:
        if c["language"] not in (None, "english") or c["kind"] == "translation":
            c["reason"] = f"translation ({c['language']})"
        elif c["names_other_hospital"]:
            c["reason"] = _other_hospital_reason(c)
        elif c["score"] < PDF_MIN_SCORE:
            c["reason"] = f"score {c['score']} < {PDF_MIN_SCORE}"
        else:
            c["reason"] = "eligible"
    eligible = sorted((c for c in pdfs if c["reason"] == "eligible"), key=lambda c: (-c["rank"], c["url"]))
    for i, c in enumerate(eligible):
        c["reason"] = "selected" if i < MAX_DOCS else f"over the {MAX_DOCS}-document cap"
    eligible_pages = sorted((c for c in pages if c["score"] >= FOLLOW_MIN_SCORE and not c["names_other_hospital"]),
                            key=lambda c: (-c["rank"], c["url"]))
    for c in pages:
        c["reason"] = _other_hospital_reason(c) if c["names_other_hospital"] else f"score {c['score']} < {FOLLOW_MIN_SCORE}"
    for i, c in enumerate(eligible_pages):
        c["reason"] = "selected" if i < MAX_PAGES_KEPT else f"over the {MAX_PAGES_KEPT}-page cap"
    for c in rows:
        c["selected"] = c.get("reason") == "selected"
    rows.sort(key=lambda c: (not c["selected"], c["kind"], -c["rank"], c["url"]))
    return {"pages_visited": crawled["pages"], "languages_seen": sorted(langs), "candidates": rows}


def n_docs(res: dict) -> int:
    """Selected PDF and Word documents in a select() result."""
    return sum(c["selected"] and c["kind"] in DOC_KINDS for c in res["candidates"])


def n_pages(res: dict) -> int:
    """Selected web pages in a select() result."""
    return sum(c["selected"] and c["kind"] == "html" for c in res["candidates"])


def n_selected(res: dict) -> int:
    return sum(c["selected"] for c in res["candidates"])


# ---------------------------------------------------------------------------------------------------------------
# sources.csv and the saved landing page

def update_sources(results: dict[str, dict]) -> int:
    """Replace this script's rows for the hospitals just discovered; keep every other row."""
    rows = read_sources()
    keep = [r for r in rows if not (r.get("label", "").startswith(DISCOVERED_LABEL) and r["hospital_id"] in results)]
    have = {(r["hospital_id"], r["url"].strip()) for r in keep}
    new = []
    for hid in sorted(results):
        for c in results[hid]["candidates"]:
            if c["selected"] and (hid, c["url"]) not in have:
                # A web page found by the browser is fetched by the browser too: plain HTTP would get the page
                # before its scripts fill it in.
                label = f"{DISCOVERED_LABEL} {c['kind']}" + (BROWSER_SUFFIX if c.get("via_browser") and c["kind"] == "html" else "")
                new.append({"hospital_id": hid, "url": c["url"], "label": label})
                have.add((hid, c["url"]))
    write_sources(keep + new)
    return len(new)


def _saved_landing(hid: str, url: str) -> bytes | None:
    """The landing page as `hfal fetch` last saved it, if it was fetched successfully."""
    for item in latest_manifest(hid):
        if item["url"] == url and item.get("ext") == "html":
            f = paths.RAW / hid / "files" / f"{item['sha8']}.html"
            if f.exists():
                return f.read_bytes()
    return None


def load_hospitals() -> dict[str, dict]:
    """data/hospitals.csv by hospital_id, or {} if missing (then the health-system name filter is off)."""
    return hospitals.by_id()


# ---------------------------------------------------------------------------------------------------------------
# All hospitals

def _polite_getter(raw_get: Callable[[str], tuple], robots, cfg: dict, ignored: list[str]) -> Getter:
    """Wrap a raw request function with the robots.txt rule, the delay between requests and error recording.
    raw_get(url) -> (status, content_type, body); any exception becomes a recorded "error: ..." status."""
    def get(url: str) -> tuple:
        if not robots.allowed(url):
            if cfg["respect_robots"]:
                return "robots_disallowed", "", b""
            ignored.append(url)
        time.sleep(cfg["delay_seconds"])
        try:
            return raw_get(url)
        except Exception as e:  # network errors are recorded, never fatal
            return f"error: {type(e).__name__}", "", b""
    return get


def _with_saved_landing(get: Getter, landing: str, saved: bytes) -> Getter:
    """A getter that answers the landing page from the saved copy and everything else live."""
    return lambda u: (200, "text/html", saved) if u == landing else get(u)


def _discover_one(hid: str, landings: list[str], get: Getter, bget: Getter | None, nf: dict | None,
                  ignored: list[str]) -> dict:
    """Crawl and select for one hospital: plain HTTP first, the browser's crawl when plain HTTP finds no document."""
    merged = {"pages": [], "candidates": []}
    warnings = []
    for landing in landings:
        saved = _saved_landing(hid, landing)
        if saved is not None and not page_links(saved, landing):
            warnings.append(f"saved landing page has no links (bot check?); fetched live: {landing}")
            saved = None
        live = _with_saved_landing(get, landing, saved) if saved is not None else get
        c = crawl(landing, live)
        merged["pages"] += c["pages"]
        merged["candidates"] += c["candidates"]
    res = select(merged, landings[0], nf)
    browser_note = {"tried": False}
    if bget is not None and n_docs(res) == 0:
        # Plain HTTP found no PDF or Word document: crawl again, rendering every page in the browser
        # (pages built by JavaScript, bot checks that a real browser passes without a CAPTCHA).
        bres = select(crawl_all(landings, bget), landings[0], nf)
        used = n_docs(bres) > 0 or (n_selected(res) == 0 and n_selected(bres) > 0)
        browser_note = {"tried": True, "used": used, "plain_docs": 0, "browser_docs": n_docs(bres),
                        "browser_pages_visited": bres["pages_visited"]}
        if used:
            for cand in bres["candidates"]:
                cand["via_browser"] = True
            res = bres
    res.update(hospital_id=hid, landing=landings, warnings=warnings, robots_txt_ignored=sorted(set(ignored)),
               browser=browser_note, discovered_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return res


def discover_all(only: set[str] | None = None) -> None:
    from .fetch import Robots, _make_browser, make_client      # fetch imports page_links from here: import late

    cfg = paths.settings()["fetch"]
    out_dir = paths.DATA / "discovered"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    table = load_hospitals()
    if not table:
        print("note: data/hospitals.csv missing; health-system name filter is off")
    browser = _make_browser(cfg)
    with make_client(cfg["timeout_seconds"]) as client, (browser or nullcontext()):
        robots = Robots(client)
        ignored: list[str] = []     # pages fetched although robots.txt disallows them (respect_robots: false)

        def plain(url):
            r = client.get(url)
            return r.status_code, r.headers.get("content-type", ""), r.content

        get = _polite_getter(plain, robots, cfg, ignored)
        bget = _polite_getter(browser.get, robots, cfg, ignored) if browser is not None else None
        for hid, landings in sorted(landing_urls(only).items()):
            ignored.clear()
            res = _discover_one(hid, landings, get, bget, name_filter(hid, table), ignored)
            write_json(out_dir / f"{hid}.json", res, ensure_ascii=False)
            results[hid] = res
            n_other = sum(bool(c.get("names_other_hospital")) for c in res["candidates"])
            print(f"{hid}  pages={len(res['pages_visited'])}  docs={n_docs(res)}  html={n_pages(res)}  "
                  f"languages={len(res['languages_seen'])}  dropped_other_hospital={n_other}")
    added = update_sources(results)
    print(f"added {added} rows to {paths.DATA / 'sources.csv'}")
