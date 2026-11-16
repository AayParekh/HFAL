"""Reading a run folder: runs/{run_id}/, one JSON file per hospital plus a few run-level files.

A hospital's answer file is named {hospital_id}.json and always carries "hospital_id" and "answers". The run-level
files (RUN_FILES) are written by `hfal ask`, `hfal score` and scripts/final_run.py; final_check.json also has an
"answers" key (the answer counts), which is why hospital files are told apart by name AND by content.
"""

from pathlib import Path
from typing import Iterator

from . import paths
from .files import read_json

# Files in a run folder that are not a hospital's answers.
RUN_FILES = frozenset({"failed.json", "skipped.json", "usage.json", "final_run.json", "final_check.json",
                       "sample.json", "summary.json", "monitor.json", "judge_skipped.json"})


def run_dir(run_id: str, must_exist: bool = False) -> Path:
    d = paths.RUNS / run_id
    if must_exist and not d.is_dir():
        raise SystemExit(f"{d} not found")
    return d


def hospital_files(run_id_or_dir: str | Path) -> list[Path]:
    """The hospital answer files of a run, sorted by name; run-level files left out."""
    d = Path(run_id_or_dir) if isinstance(run_id_or_dir, Path) else paths.RUNS / run_id_or_dir
    return [p for p in sorted(d.glob("*.json")) if p.name not in RUN_FILES]


def hospital_records(run_id_or_dir: str | Path) -> Iterator[tuple[str, dict]]:
    """(hospital_id, the run's JSON for it) for every hospital answer file of a run, in file order."""
    for p in hospital_files(run_id_or_dir):
        data = read_json(p)
        if "answers" in data and "hospital_id" in data:
            yield data["hospital_id"], data


def answers_by_criterion(data: dict) -> dict[str, dict]:
    """criterion_id -> answer record, the shape grade.grade_hospital takes."""
    return {a["criterion_id"]: a for a in data.get("answers", [])}
