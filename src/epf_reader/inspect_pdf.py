#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""Report what a passbook PDF actually is, so the extraction path isn't a guess.

Answers, per page: is there a text layer, how much of it, are there ruled table
lines, and how many rows each available backend would return. Needs only
pdfplumber — no Tesseract, no Java.

    python3 inspect_pdf.py passbook.pdf
    python3 inspect_pdf.py passbook.pdf --password SECRET
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("pdfplumber is required:  pip install pdfplumber")
    raise SystemExit(1)

# Same threshold pdf_analyzer.check_if_text_based() uses to call a page "text".
TEXT_CHARS_THRESHOLD = 100
CHAR_OBJECTS_THRESHOLD = 50



def _looks_encrypted(pdf_path: Path) -> bool:
    """True if the PDF declares an /Encrypt dictionary.

    Checked against the file's own bytes rather than the exception text:
    pdfplumber raises with an empty message on a password-protected file, so
    message sniffing silently misreports it as a generic open failure.
    """
    try:
        with open(pdf_path, "rb") as fh:
            return b"/Encrypt" in fh.read()
    except OSError:
        return False


def inspect(pdf_path: Path, password: str = "") -> int:
    print(f"{pdf_path.name}  ({pdf_path.stat().st_size / 1024:.0f} KB)")
    print("=" * 72)

    try:
        pdf_cm = pdfplumber.open(pdf_path, password=password)
    except Exception as exc:
        if _looks_encrypted(pdf_path):
            if password:
                print("Opening failed with the password given — it looks wrong.")
            else:
                print("This PDF is encrypted. Re-run with --password <pw>.")
                print("(EPFO passbook downloads are usually not encrypted; CAMS/bank ones are.)")
            return 1
        detail = str(exc) or f"{type(exc).__name__} (no message)"
        print(f"Could not open the PDF: {detail}")
        return 1

    with pdf_cm as pdf:
        pages = pdf.pages
        print(f"Pages: {len(pages)}\n")

        text_pages = 0
        header = f"{'page':>5}  {'chars':>7}  {'words':>6}  {'lines':>6}  {'rects':>6}  {'verdict':<10}  rows(lines/text)"
        print(header)
        print("-" * len(header))

        for i, page in enumerate(pages, 1):
            text = page.extract_text() or ""
            n_chars = len(page.chars or [])
            n_words = len((page.extract_words() or []))
            n_lines = len(page.lines or [])
            n_rects = len(page.rects or [])

            is_text = len(text.strip()) > TEXT_CHARS_THRESHOLD or n_chars > CHAR_OBJECTS_THRESHOLD
            text_pages += bool(is_text)

            rows = {}
            for label, settings in (
                ("lines", {"vertical_strategy": "lines", "horizontal_strategy": "lines"}),
                ("text", {"vertical_strategy": "text", "horizontal_strategy": "text"}),
            ):
                try:
                    tables = page.extract_tables(table_settings=settings) or []
                    rows[label] = max((len(t) for t in tables), default=0)
                except Exception:
                    rows[label] = -1

            print(
                f"{i:>5}  {n_chars:>7}  {n_words:>6}  {n_lines:>6}  {n_rects:>6}  "
                f"{'TEXT' if is_text else 'SCANNED':<10}  {rows['lines']}/{rows['text']}"
            )

        print()
        first = pages[0]
        sample = (first.extract_text() or "")[:400]
        if sample.strip():
            print("First page text (first 400 chars) — confirm it reads as a passbook:")
            print("-" * 72)
            print(sample)
            print("-" * 72)
        else:
            print("First page has no extractable text at all → scanned.")

        print()
        if text_pages == len(pages):
            print("VERDICT: text-based on every page.")
            print("  -> pdfplumber or tabula will read it. OCR (Tesseract) is NOT needed.")
        elif text_pages == 0:
            print("VERDICT: scanned on every page.")
            print("  -> OCR is required: brew install tesseract poppler, then --method ocr")
        else:
            print(f"VERDICT: mixed — {text_pages}/{len(pages)} page(s) have a text layer.")
            print("  -> Install the OCR deps; the scanned pages need them.")

        print()
        print("The rows(lines/text) column shows how many table rows each pdfplumber")
        print("strategy finds. A healthy text passbook shows a double-digit count in")
        print("at least one of them; 0/0 on a TEXT page means the text is there but")
        print("not laid out as a detectable table.")

    return 0


def main() -> int:
    args = sys.argv[1:]
    password = ""
    if "--password" in args:
        i = args.index("--password")
        try:
            password = args[i + 1]
        except IndexError:
            print("--password needs a value")
            return 2
        del args[i : i + 2]

    if len(args) != 1:
        print(f"usage: {Path(sys.argv[0]).name} <passbook.pdf> [--password PW]")
        return 2

    path = Path(args[0]).expanduser()
    if not path.is_file():
        print(f"not found: {path}")
        return 1
    return inspect(path, password)


if __name__ == "__main__":
    raise SystemExit(main())
