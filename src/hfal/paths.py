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


def criteria() -> list[dict]:
    return load_yaml("criteria.yaml")["criteria"]


def rubric() -> dict:
    return load_yaml("rubric.yaml")
