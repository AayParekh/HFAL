"""Rebuild config/reference/uniform_application.txt from the saved Word file of the state's uniform application.

Run by hand after replacing the Word file:  uv run python scripts/build_reference_form.py

The text is made once, with the same extractor the hospital documents go through, and saved. The model is then
given this text (never the original file), so the form is read and tokenized as ordinary text and nothing is re-extracted per
hospital. The output uses the same [[page N]] markers as `ask.render_documents`.
"""
import hashlib
from pathlib import Path

from hfal.extract import extract_docx

REF = Path(__file__).resolve().parents[1] / "config" / "reference"
SRC = REF / "2025_uniform_financial_assistance_application.docx"
OUT = REF / "uniform_application.txt"


def main() -> None:
    pages, needs_ocr = extract_docx(SRC)
    if needs_ocr:
        raise SystemExit(f"{SRC.name} has no text")
    OUT.write_text("\n".join(f"[[page {i}]]\n{p.strip()}\n" for i, p in enumerate(pages, start=1)), encoding="utf-8")
    sha = hashlib.sha256(SRC.read_bytes()).hexdigest()
    print(f"{OUT.name}: {len(pages)} pages, {OUT.stat().st_size} characters, from {SRC.name} (sha256 {sha[:12]})")


if __name__ == "__main__":
    main()
