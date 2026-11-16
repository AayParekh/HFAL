"""Where things live, and the configuration files: settings.yaml, the criteria file, rubric.yaml.

Everything under data/ and runs/ is git-ignored (CLAUDE.md, DATA HANDLING). Tests point these constants at temporary
folders, so other modules must read them through this module (paths.RUNS, never a copy taken at import time).
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
RAW = DATA / "raw"
TEXT = DATA / "text"
TAGS = DATA / "tags"
CACHE = DATA / "cache"
GOLDEN = ROOT / "golden"
RUNS = ROOT / "runs"
MANUAL = DATA / "manual"

DEFAULT_CRITERIA_FILE = "criteria.yaml"     # the generated v5 criteria


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Model presets chosen on the command line (`--model NAME`), by section: {"model": "kimi-k3", "judge": ...}.
# For the rest of the command, settings() returns that preset from settings.yaml `models:` in place of the section.
_PRESETS: dict[str, str] = {}


def use_model(section: str, preset: str) -> None:
    """Use settings.yaml `models.<preset>` as the `model` (checker) or `judge` section for this command."""
    presets = load_yaml("settings.yaml").get("models") or {}
    if preset not in presets:
        raise SystemExit(f"--model {preset}: not one of the presets in settings.yaml `models:` "
                         f"({', '.join(sorted(presets)) or 'none defined'})")
    _PRESETS[section] = preset


def settings() -> dict:
    cfg = load_yaml("settings.yaml")
    for section, preset in _PRESETS.items():
        cfg[section] = {**cfg["models"][preset], "preset": preset}
    return cfg


def criteria_file() -> str:
    """settings.yaml `criteria_file` (default criteria.yaml, the generated v5 criteria)."""
    return settings().get("criteria_file", DEFAULT_CRITERIA_FILE)


def _criteria_doc() -> dict:
    """The whole criteria file, or {} when the file named in settings does not exist (the prompt then has no reading
    rules, no consistency points and no reference material, which is how versions before v5 were built)."""
    try:
        return load_yaml(criteria_file()) or {}
    except FileNotFoundError:
        return {}


def criteria() -> list[dict]:
    """The criteria the pipeline asks about (a missing file is an error here: nothing can run without them)."""
    return load_yaml(criteria_file())["criteria"]


def reading_rules() -> str:
    """Rules for reading the documents that apply to every criterion; appended to the system prompt. May be empty."""
    return (_criteria_doc().get("reading_rules") or "").strip()


def consistency_points() -> list[dict]:
    """`consistency_points` from the criteria file (prompt v7 on): the points compared one by one for
    consistent_across_posted_documents, each {id, text, counts}. Empty for a criteria file without them."""
    return _criteria_doc().get("consistency_points") or []


def reference_form() -> str:
    """The state's blank application as text, when the criteria file names one (`reference_form`, a path inside
    config/). Empty for a criteria file without it."""
    name = _criteria_doc().get("reference_form")
    return (CONFIG / name).read_text(encoding="utf-8").strip() if name else ""


def reference_fpl() -> str:
    """`reference_fpl` from the criteria file (a path inside config/), or empty: the poverty figures go in the prompt."""
    return _criteria_doc().get("reference_fpl") or ""


def rubric() -> dict:
    return load_yaml("rubric.yaml")
