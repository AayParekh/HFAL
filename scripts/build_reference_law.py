"""Rebuild config/reference/phl_2807k_9a.txt: the text of New York Public Health Law § 2807-k, subdivisions 9 and 9-a
(the Hospital Financial Assistance Law), from newyork.public.law.

Run by hand when the law changes:  uv run python scripts/build_reference_law.py

The page shows two dates for the law, each in two places:
  * "Verified" (the day the site last checked its copy against the official source) and "Last modified" (the day the
    official text last changed), in the sidebar card;
  * the same two dates in the citation at the foot of the page: "(updated <last modified>; accessed <verified>)".
The script reads both places and stops if they disagree or one is missing, so a change in the site's layout cannot
silently give a wrong date. The HTTP Last-Modified header is NOT used: it dates the web page, not the law.

Only the statute text and its dates are saved (no HTML from the site). The official source is the New York State
Senate's copy, linked from the page and recorded in the header of the output.
"""
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from hfal import paths
from hfal.fetch import Robots, make_client

URL = "https://newyork.public.law/laws/n.y._public_health_law_section_2807-k"
OUT = paths.CONFIG / "reference" / "phl_2807k_9a.txt"
FIRST, STOP = "9.", "10."          # keep subdivision 9 (uniform form) and 9-a (financial assistance); stop at 10


def parse_date(text: str) -> date:
    """'Nov. 10, 2026', 'May 29, 2026', 'Sept. 3, 2026', 'September 3, 2026' -> date."""
    t = re.sub(r"\s+", " ", text.replace(".", "")).strip()
    t = re.sub(r"^Sept\b", "Sep", t)
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"not a date: {text!r}")


def card_dates(soup: BeautifulSoup) -> dict[str, date]:
    """The sidebar card: <strong>Verified:</strong><br>Nov. 10, 2026 (and the same for Last modified)."""
    out = {}
    for label, key in (("Verified:", "verified"), ("Last modified:", "last_modified")):
        found = [s for s in soup.find_all("strong") if s.get_text(strip=True) == label]
        if len(found) != 1:
            raise SystemExit(f"expected one '{label}' in the page, found {len(found)}: the layout changed, check by hand")
        p = found[0].find_parent("p")
        out[key] = parse_date(p.get_text(" ", strip=True).replace(label, "", 1))
    return out


def footer_dates(soup: BeautifulSoup) -> tuple[dict[str, date], str]:
    """The citation at the foot: '... <official url> (updated May 29, 2026; accessed Nov. 10, 2026).'"""
    link = soup.find("a", id="footer-source-link")
    if link is None:
        raise SystemExit("no footer source link in the page: the layout changed, check by hand")
    cite = link.find_parent("cite").get_text(" ", strip=True)
    m = re.search(r"\(updated ([^;]+); accessed ([^)]+)\)", cite)
    if not m:
        raise SystemExit(f"footer citation has no '(updated ...; accessed ...)': {cite!r}")
    return {"last_modified": parse_date(m.group(1)), "verified": parse_date(m.group(2))}, link["href"]


def dates(soup: BeautifulSoup) -> tuple[dict[str, date], str]:
    card = card_dates(soup)
    foot, official = footer_dates(soup)
    if card != foot:
        raise SystemExit(f"the page disagrees with itself: card {card}, footer {foot}. Check by hand.")
    return card, official


def statute_lines(soup: BeautifulSoup) -> list[str]:
    """Subdivisions 9 and 9-a, one line per lettered or numbered part.

    The site shows each cross-reference twice: its own label (<a class="pragmatic">, "§ 12 (Violations of health laws
    or regulations)") and the statute's words (<a class="pedantic">, "section twelve of this chapter"). Only the
    statute's words are kept. Every part of 9-a gets the same indent: the site's outline levels are uneven (its
    (i)/(ii) and (iii) of the same paragraph sit at different levels), and the labels already show the structure.
    """
    for a in soup.select("a.pragmatic"):
        a.decompose()
    lines, on = [], False
    for sec in soup.select("section.non-meta.outline"):
        head = sec.find(re.compile(r"^h\d$"))
        label = head.get_text(strip=True) if head else ""
        level = int(re.search(r"level-(\d)", " ".join(sec.get("class", []))).group(1))
        if level == 0 and label == STOP and on:
            break
        if level == 0 and label == FIRST:
            on = True
        if not on:
            continue
        if head:
            head.extract()
        text = re.sub(r"\s+", " ", sec.get_text(" ", strip=True)).strip()
        text = re.sub(r"\s+([,.;:)])", r"\1", text)
        text = re.sub(r"\(\s+", "(", text)
        if label == FIRST and text.endswith(" 9-a."):      # the site puts the "9-a." heading at the end of 9
            lines += [f"{label} {text[:-len(' 9-a.')]}", "", "9-a."]
            continue
        lines.append(("" if level == 0 else "  ") + f"{label} {text}")
    if not on or len(lines) < 10:
        raise SystemExit("did not find subdivisions 9 and 9-a: the layout changed, check by hand")
    return lines


def build(html: str, retrieved: date) -> str:
    soup = BeautifulSoup(html, "html.parser")
    d, official = dates(soup)
    head = [
        "New York Public Health Law § 2807-k, subdivisions 9 and 9-a (Hospital Financial Assistance Law)",
        f"Source: {URL}",
        f"Official source: {official}",
        f"Law last modified: {d['last_modified'].isoformat()}",
        f"Verified by source against the official text: {d['verified'].isoformat()}",
        f"Retrieved: {retrieved.isoformat()}",
        "Built by scripts/build_reference_law.py. Do not edit by hand.",
        "",
    ]
    return "\n".join(head + statute_lines(soup)) + "\n"


def main() -> None:
    with make_client(timeout=30) as client:
        if not Robots(client).allowed(URL):
            raise SystemExit(f"robots.txt disallows {URL}")
        r = client.get(URL)
        r.raise_for_status()
    text = build(r.text, date.today())
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT.name}: {len(text.splitlines())} lines, {len(text)} characters")
    print("\n".join(text.splitlines()[2:6]))


if __name__ == "__main__":
    main()
