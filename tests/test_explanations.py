import copy
import importlib.util
from datetime import date
from pathlib import Path

import pytest
import yaml

from hfal import explain

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("build_reference_law", ROOT / "scripts" / "build_reference_law.py")
build_law = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_law)

LAW = """Header: x

9. Hospitals must use the uniform form.

9-a.
  (a) Paragraph a text.
  (b) Paragraph b text:
  (i) first sub of b;
  (ii) second sub of b.
  (c) Paragraph c text.
  (d) Paragraph d.
  (e) Paragraph e.
  (f) Paragraph f.
  (g) Paragraph g.
  (h) Paragraph h.
  (i) Paragraph i itself:
  (i) sub one of i;
  (ii) sub two of i.
  (j) Paragraph j.
"""


def test_law_parts_tells_paragraph_i_from_subparagraph_i():
    p = explain.law_parts(LAW)
    assert p["9"].startswith("Hospitals must use")
    assert p["9-a(b)(i)"] == "first sub of b;"
    assert "second sub of b." in p["9-a(b)"]                # a paragraph includes its subparagraphs
    assert p["9-a(i)"].startswith("Paragraph i itself")
    assert p["9-a(i)(i)"] == "sub one of i;"
    assert p["9-a(j)"] == "Paragraph j."
    assert "9-a(b)(iii)" not in p


def test_citation_format():
    assert explain.citation("9-a(e)(ii)") == "N.Y. Public Health Law § 2807-k(9-a)(e)(ii)"
    assert explain.citation("9") == "N.Y. Public Health Law § 2807-k(9)"
    with pytest.raises(ValueError):
        explain.citation("9-a e")


def test_real_templates_quote_the_real_law():
    """Every quote in config/explanations.yaml is in the part of the saved law it cites."""
    assert explain.check(explain.load(), explain.LAW.read_text(encoding="utf-8")) == []


@pytest.mark.skipif(not (ROOT / "config" / "criteria.yaml").exists(), reason="needs the generated criteria.yaml")
def test_one_template_per_criterion():
    crit = yaml.safe_load((ROOT / "config" / "criteria.yaml").read_text(encoding="utf-8"))["criteria"]
    ids = [c["id"] for c in crit]
    assert explain.check(explain.load(), explain.LAW.read_text(encoding="utf-8"), ids) == []


def test_check_catches_a_misquote_a_wrong_part_and_a_missing_field():
    law = explain.LAW.read_text(encoding="utf-8")
    t = copy.deepcopy(explain.load())
    c = t["criteria"]
    c["no_time_limit_to_submit"]["law"][0]["quote"] = "patients may apply within 240 days"
    c["no_mention_of_immigration_status_as_a_barrier"]["law"][0]["cite"] = "9-a(b)"   # real quote, wrong part
    c["max_fpl"]["law"][0]["cite"] = "9-a(z)"
    del c["max_fpl"]["why_it_matters"]
    problems = explain.check(t, law, list(c) + ["made_up_criterion"])
    text = "\n".join(problems)
    assert "no_time_limit_to_submit: law[0] quote is not found word for word in 9-a(e)" in text
    assert "no_mention_of_immigration_status_as_a_barrier: law[0] quote is not found word for word in 9-a(b)" in text
    assert "max_fpl: law[0] cites '9-a(z)'" in text
    assert "max_fpl: missing why_it_matters" in text
    assert "made_up_criterion: no template" in text


def test_templates_never_call_not_found_a_failure():
    common = explain.load()["common"]["NOT_FOUND"].lower()
    assert "does not mean the hospital fails" in common


# --- scripts/build_reference_law.py, on an invented page in the site's layout ---------------------------------------

def page(verified="Nov. 10, 2026", modified="May 29, 2026", foot=("May 29, 2026", "Nov. 10, 2026")):
    return f"""<html><body>
<section class="level-0 non-meta outline"><h2>8.</h2> Eight.</section>
<section class="level-0 non-meta outline"><h2>9.</h2> Use only the uniform form. 9-a.</section>
<section class="level-1 non-meta outline"><h3>(a)</h3> Immigration status is not a criterion.</section>
<section class="level-1 non-meta outline"><h3>(b)</h3> Discounts:</section>
<section class="level-1 non-meta outline"><h3>(i)</h3> waive below 200 ;</section>
<section class="level-2 non-meta outline"><h4>(ii)</h4> see <a class="pragmatic" href="/x">§ 12 (Violations)</a><a class="pedantic" href="/x">section twelve of this chapter</a>.</section>
<section class="level-1 non-meta outline"><h3>(c)</h3> c1.</section>
<section class="level-1 non-meta outline"><h3>(d)</h3> d1.</section>
<section class="level-1 non-meta outline"><h3>(e)</h3> e1.</section>
<section class="level-1 non-meta outline"><h3>(f)</h3> f1.</section>
<section class="level-1 non-meta outline"><h3>(g)</h3> g1.</section>
<section class="level-0 non-meta outline"><h2>10.</h2> Ten.</section>
<div><p><strong>Verified:</strong><br>{verified}</p><p><strong>Last modified:</strong><br>{modified}</p></div>
<cite>Source <a id="footer-source-link" href="https://www.nysenate.gov/legislation/laws/PBH/2807-K">link</a>
 (updated {foot[0]}; accessed {foot[1]}).</cite>
</body></html>"""


def test_build_reads_both_dates_and_the_official_source():
    out = build_law.build(page(), date(2026, 11, 11))
    assert "Law last modified: 2026-05-29" in out
    assert "Verified by source against the official text: 2026-11-10" in out
    assert "Retrieved: 2026-11-11" in out
    assert "Official source: https://www.nysenate.gov/legislation/laws/PBH/2807-K" in out


def test_build_keeps_9_and_9a_only_and_the_statutes_own_words():
    out = build_law.build(page(), date(2026, 11, 11))
    assert "9. Use only the uniform form.\n\n9-a.\n" in out
    assert "  (a) Immigration status is not a criterion." in out
    assert "  (ii) see section twelve of this chapter." in out        # the site's own label is dropped
    assert "Violations" not in out and "Eight" not in out and "Ten" not in out
    assert "  (i) waive below 200;" in out
    assert explain.law_parts(out)["9-a(b)(ii)"] == "see section twelve of this chapter."


def test_build_refuses_when_the_page_disagrees_with_itself():
    with pytest.raises(SystemExit, match="disagrees"):
        build_law.build(page(verified="Nov. 9, 2026"), date(2026, 11, 11))
    with pytest.raises(SystemExit, match="disagrees"):
        build_law.build(page(foot=("May 28, 2026", "Nov. 10, 2026")), date(2026, 11, 11))


def test_build_refuses_when_a_date_is_missing():
    with pytest.raises(SystemExit, match="Verified"):
        build_law.build(page().replace("<strong>Verified:</strong>", ""), date(2026, 11, 11))


@pytest.mark.parametrize("text,expected", [
    ("Nov. 10, 2026", date(2026, 11, 10)), ("May 29, 2026", date(2026, 5, 29)),
    ("Sept. 3, 2026", date(2026, 9, 3)), ("September 3, 2026", date(2026, 9, 3)), ("Jan.  5, 2027", date(2027, 1, 5)),
])
def test_parse_date(text, expected):
    assert build_law.parse_date(text) == expected
