"""Plain-language explanations of each criterion, from hand-written templates (config/explanations.yaml).

No model writes or changes these texts. Each template cites the part of New York Public Health Law § 2807-k it rests
on and quotes it; `check` proves every quote appears word for word in that part of the saved law text
(config/reference/phl_2807k_9a.txt, built by scripts/build_reference_law.py), the same way answer quotes are
verified against hospital documents.
"""
import re
from pathlib import Path

import yaml

from . import paths

TEMPLATES = paths.CONFIG / "explanations.yaml"
LAW = paths.CONFIG / "reference" / "phl_2807k_9a.txt"

BASES = {"law", "law_and_state_form", "review_standard"}
FIELDS = ("title", "basis", "law", "rule", "why_it_matters", "if_yes", "if_no")
RESULTS = ("UNCLEAR", "NOT_FOUND", "N/A")
ROMAN = re.compile(r"^\((?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\)$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def law_parts(text: str) -> dict[str, str]:
    """Map each part of the saved law text to its words: '9', '9-a(a)', '9-a(e)', '9-a(e)(ii)', ...

    A paragraph's entry includes its subparagraphs, so a quote from 9-a(b)(i) is also found under 9-a(b). Labels
    such as "(i)" are ambiguous (paragraph i, or subparagraph i): a label is the next paragraph only when it is
    the letter after the current one, otherwise it is a subparagraph of the current paragraph.
    """
    parts: dict[str, list[str]] = {}
    sub, letter, para = None, None, None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^(\d+(?:-[a-z])?)\.(?:\s+(.*))?$", line)
        if m:                                             # "9. In order ..." or "9-a."
            sub, letter, para = m.group(1), None, None
            parts.setdefault(sub, []).append(m.group(2) or "")
            continue
        m = re.match(r"^(\([a-z]+\))\s+(.*)$", line)
        if not (m and sub):
            continue
        label, body = m.groups()
        expected = "(a)" if letter is None else f"({chr(ord(letter[1]) + 1)})"
        if label == expected or (letter is None and not ROMAN.match(label)):
            letter, key = label, f"{sub}{label}"
            para = key
        else:                                             # a subparagraph of the current paragraph
            key = f"{para}{label}"
            parts.setdefault(para, []).append(body)
        parts.setdefault(key, []).append(body)
        parts.setdefault(sub, []).append(body)
    return {k: _norm(" ".join(v)) for k, v in parts.items()}


def law_header(text: str) -> dict[str, str]:
    """The 'Key: value' lines at the top of the saved law text (source, dates)."""
    out = {}
    for line in text.splitlines():
        if not line.strip():
            break
        if ": " in line:
            k, v = line.split(": ", 1)
            out[k.strip()] = v.strip()
    return out


def citation(cite: str) -> str:
    """'9-a(e)' -> 'N.Y. Public Health Law § 2807-k(9-a)(e)'."""
    m = re.match(r"^(\d+(?:-[a-z])?)((?:\([a-z]+\))*)$", cite)
    if not m:
        raise ValueError(f"not a citation: {cite!r}")
    return f"N.Y. Public Health Law § 2807-k({m.group(1)}){m.group(2)}"


def load(path: Path = TEMPLATES) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check(templates: dict, law_text: str, criteria_ids: list[str] | None = None) -> list[str]:
    """Problems with the templates, as plain sentences. Empty list = all good."""
    problems = []
    parts = law_parts(law_text)
    common = templates.get("common") or {}
    for r in RESULTS:
        if not str(common.get(r) or "").strip():
            problems.append(f"common: no text for {r}")
    crit = templates.get("criteria") or {}
    for cid, t in crit.items():
        for f in FIELDS:
            if not t.get(f):
                problems.append(f"{cid}: missing {f}")
        if t.get("basis") and t["basis"] not in BASES:
            problems.append(f"{cid}: basis {t['basis']!r} is not one of {sorted(BASES)}")
        for i, ref in enumerate(t.get("law") or []):
            cite, quote = ref.get("cite", ""), _norm(ref.get("quote", ""))
            if cite not in parts:
                problems.append(f"{cid}: law[{i}] cites {cite!r}, which is not a part of the saved law text")
            elif not quote or quote not in parts[cite]:
                problems.append(f"{cid}: law[{i}] quote is not found word for word in {cite}")
    if criteria_ids is not None:
        for cid in sorted(set(criteria_ids) - set(crit)):
            problems.append(f"{cid}: no template")
        for cid in sorted(set(crit) - set(criteria_ids)):
            problems.append(f"{cid}: template for a criterion that does not exist")
    return problems
