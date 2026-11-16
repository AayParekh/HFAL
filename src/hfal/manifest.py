"""Reading a hospital's fetch manifests: data/raw/{hospital_id}/{date}/manifest.json, one per `hfal fetch` day.

A manifest is a list of entries, one per URL (or manual file): url, label, fetched_at, status, and when the download
succeeded sha8 / sha256 / ext / bytes / change (fetch.py documents the fields). The newest manifest is the one that
decides which documents `ask` sees; older ones stay on disk for the monthly diff.
"""

from pathlib import Path

from . import paths
from .files import read_json


def manifest_files(hospital_id: str) -> list[Path]:
    """Every manifest of the hospital, oldest first (the folder names are ISO dates, so they sort by date)."""
    return sorted((paths.RAW / hospital_id).glob("*/manifest.json"))


def full_manifest(hospital_id: str) -> list[dict]:
    """The hospital's latest manifest, every entry whatever its status; [] when it was never fetched."""
    files = manifest_files(hospital_id)
    return read_json(files[-1]) if files else []


def latest_manifest(hospital_id: str) -> list[dict]:
    """The entries of the latest manifest that were downloaded (status ok)."""
    return [e for e in full_manifest(hospital_id) if e.get("status") == "ok"]


def latest_before(hospital_id: str, day: str) -> tuple[str | None, list[dict]]:
    """(date, entries) of the hospital's latest manifest dated before `day` (an ISO date); (None, []) if none."""
    for m in reversed(manifest_files(hospital_id)):
        if m.parent.name < day:
            return m.parent.name, read_json(m)
    return None, []


def previous_sha(hospital_id: str, url: str) -> str | None:
    """The sha8 this URL last downloaded as, across every manifest; None if it was never stored."""
    last = None
    for m in manifest_files(hospital_id):
        for entry in read_json(m):
            if entry["url"] == url and entry.get("sha8"):
                last = entry["sha8"]
    return last
