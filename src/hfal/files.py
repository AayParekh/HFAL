"""Small file helpers shared by the whole package: CSV and JSON reading and writing, and atomic writes.

Every module used to open its own files with the same four lines. Keeping them here means one place decides the
encoding, the line ending and how a half-written file is avoided.

Encodings. Our own CSV files are UTF-8. Files a person opens in Excel (review sheets, the results report) are written
as UTF-8 with a byte-order mark ("utf-8-sig"), which makes Excel show accents right; reading with "utf-8-sig"
accepts both kinds, so every reader here uses it.

Atomic writes. write_atomic() writes to a temporary file in the same folder and then renames it over the target, so a
run stopped part-way (Ctrl-C, a budget stop) leaves either the old file or the whole new one, never half of one. The
temporary name ends in .tmp, so it is never mistaken for a data file.
"""

import csv
import json
import os
from pathlib import Path
from typing import Iterable

UTF8 = "utf-8"
EXCEL = "utf-8-sig"      # UTF-8 with a byte-order mark: Excel shows accents right
EXCEL_HINT = "is not UTF-8. In Excel, save it as 'CSV UTF-8 (Comma delimited)' and try again."


def read_csv(path: Path, encoding: str = EXCEL) -> list[dict]:
    """The rows of a CSV file as dicts (csv.DictReader)."""
    with open(path, newline="", encoding=encoding) as f:
        return list(csv.DictReader(f))


def read_csv_with_fields(path: Path, encoding: str = EXCEL) -> tuple[list[str], list[dict]]:
    """(column names in file order, rows) of a CSV file."""
    with open(path, newline="", encoding=encoding) as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def read_sheet(path: Path) -> list[dict]:
    """A review sheet a person edited (and maybe saved from Excel). A file that is not UTF-8 is refused with a hint
    rather than guessed at: Excel's plain 'CSV (Comma delimited)' is cp1252."""
    try:
        return read_csv(path, EXCEL)
    except UnicodeDecodeError:
        raise SystemExit(f"{path} {EXCEL_HINT}") from None


def read_csv_rows(path: Path, encoding: str = EXCEL) -> list[list[str]]:
    """The raw rows of a CSV file (csv.reader), for sheets with several header rows."""
    with open(path, newline="", encoding=encoding) as f:
        return list(csv.reader(f))


def write_csv(path: Path, rows: Iterable[dict], fields: list[str], *, encoding: str = UTF8,
              extrasaction: str = "raise", atomic: bool = False) -> None:
    """Write rows as a CSV file with a header, "\\n" line endings and the given columns.

    extrasaction="ignore" drops keys that are not in `fields` (csv.DictWriter's option). atomic=True writes through a
    temporary file (see write_atomic). The parent folder is created if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.with_name(path.name + ".tmp") if atomic else path
    with open(target, "w", newline="", encoding=encoding) as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction=extrasaction, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    if atomic:
        os.replace(target, path)


def read_json(path: Path):
    """json.loads of a UTF-8 file."""
    return json.loads(Path(path).read_text(encoding=UTF8))


def read_json_or_none(path: Path):
    """json.loads of a UTF-8 file, or None when the file is missing or unreadable (the caller redoes the work)."""
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def write_json(path: Path, obj, *, indent: int | None = 2, ensure_ascii: bool = True, atomic: bool = False) -> None:
    """json.dumps to a UTF-8 file; the parent folder is created if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii)
    if atomic:
        write_atomic(path, text)
    else:
        path.write_text(text, encoding=UTF8)


def write_atomic(path: Path, text: str) -> None:
    """Write a text file so that it is either the old one or the whole new one, never half of it: a run stopped
    part-way (final_run.py's budget stop, Ctrl-C) cannot leave a half-written file that would break the next read.
    The temporary name ends in .tmp, so it is never mistaken for a data file (*.json, *.csv)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=UTF8)
    os.replace(tmp, path)
