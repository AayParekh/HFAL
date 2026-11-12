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


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def settings() -> dict:
    return load_yaml("settings.yaml")


def criteria_file() -> str:
    """settings.yaml `criteria_file` (default criteria.yaml, the generated v5 criteria)."""
    return settings().get("criteria_file", "criteria.yaml")


def criteria() -> list[dict]:
    return load_yaml(criteria_file())["criteria"]


def reading_rules() -> str:
    """Rules for reading the documents that apply to every criterion; appended to the system prompt. May be empty."""
    try:
        return (load_yaml(criteria_file()).get("reading_rules") or "").strip()
    except FileNotFoundError:
        return ""


def consistency_points() -> list[dict]:
    """`consistency_points` from the criteria file (prompt v7 on): the points compared one by one for
    consistent_across_posted_documents, each {id, text, counts}. Empty for a criteria file without them."""
    try:
        return load_yaml(criteria_file()).get("consistency_points") or []
    except FileNotFoundError:
        return []


def reference_form() -> str:
    """The state's blank application as text, when the criteria file names one (`reference_form`, a path inside
    config/). Empty for a criteria file without it."""
    try:
        name = load_yaml(criteria_file()).get("reference_form")
    except FileNotFoundError:
        return ""
    return (CONFIG / name).read_text(encoding="utf-8").strip() if name else ""


def reference_fpl() -> str:
    """`reference_fpl` from the criteria file (a path inside config/), or empty: the poverty figures go in the prompt."""
    try:
        return load_yaml(criteria_file()).get("reference_fpl") or ""
    except FileNotFoundError:
        return ""


def rubric() -> dict:
    return load_yaml("rubric.yaml")
