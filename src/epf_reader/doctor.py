#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""Preflight check for the EPF OCR extractor.

A text/table PDF needs nothing but pip packages — pdfplumber reads it directly.
Only a *scanned* passbook needs the two things pip cannot install: the Tesseract
binary and Poppler's ``pdftoppm`` (via pdf2image). The optional tabula/camelot
backends need a Java runtime and Ghostscript respectively.

So this reports two separate verdicts: ``ready`` (can read a text PDF) and
``ocr_ready`` (can also read a scanned one), rather than failing a perfectly
usable install for want of an OCR engine it will never call.

    python3 doctor.py          # human-readable report, exit 1 if unusable
    python3 doctor.py --json   # machine-readable
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys

# (import name, pip name) — required to read any PDF with a text layer.
CORE_MODULES = [
    ("pandas", "pandas"),
    ("pdfplumber", "pdfplumber"),
    ("PyPDF2", "PyPDF2"),
    ("yaml", "PyYAML"),
]

# Python packages needed only for scanned PDFs: pip install "epf-reader[ocr]"
OCR_MODULES = [
    ("cv2", "opencv-python-headless"),
    ("numpy", "numpy"),
    ("pdf2image", "pdf2image"),
    ("PIL", "Pillow"),
    ("pytesseract", "pytesseract"),
]

OPTIONAL_MODULES = [
    ("openpyxl", "openpyxl", "--excel output"),
    ("streamlit", "streamlit", "the epf-ui web page"),
    ("tabula", "tabula-py", "faster text-PDF path (needs Java)"),
    ("camelot", "camelot-py[cv]", "bordered-table path (needs Ghostscript)"),
]

# Install hints are per-platform: the same missing binary needs a different
# command on macOS and Linux, and printing the wrong one is worse than useless.
_MAC = sys.platform == "darwin"


def _hint(mac: str, linux: str) -> str:
    return mac if _MAC else linux


# (binary, what needs it, how to install it)
# Needed ONLY for scanned PDFs. A text PDF never reaches this code.
OCR_BINARIES = [
    (
        "tesseract",
        "OCR engine",
        _hint("brew install tesseract", "sudo apt install tesseract-ocr"),
    ),
    (
        "pdftoppm",
        "PDF->image (Poppler, used by pdf2image)",
        _hint("brew install poppler", "sudo apt install poppler-utils"),
    ),
]

OPTIONAL_BINARIES = [
    (
        "java",
        "tabula-py backend",
        _hint("brew install --cask temurin", "sudo apt install default-jre"),
    ),
    (
        "gs",
        "camelot lattice backend (Ghostscript)",
        _hint("brew install ghostscript", "sudo apt install ghostscript"),
    ),
]


def _probe_module(name: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(name)
    except Exception as exc:  # ImportError, but also broken native deps
        return False, str(exc).splitlines()[0]
    return True, str(getattr(mod, "__version__", "") or "")


def _probe_binary(name: str) -> tuple[bool, str]:
    path = shutil.which(name)
    if not path:
        return False, ""
    version = ""
    try:
        out = subprocess.run(
            [name, "--version"], capture_output=True, text=True, timeout=10
        )
        version = (out.stdout or out.stderr).strip().splitlines()[0][:60]
    except Exception:
        pass
    return True, version or path


def collect() -> dict:
    report: dict = {
        "python": sys.version.split()[0],
        "core_modules": {},
        "ocr_modules": {},
        "ocr_binaries": {},
        "optional_modules": {},
        "optional_binaries": {},
    }

    for name, pip_name in CORE_MODULES:
        ok, detail = _probe_module(name)
        report["core_modules"][name] = {"ok": ok, "detail": detail, "install": pip_name}

    for name, pip_name in OCR_MODULES:
        ok, detail = _probe_module(name)
        report["ocr_modules"][name] = {"ok": ok, "detail": detail, "install": pip_name}

    for name, purpose, how in OCR_BINARIES:
        ok, detail = _probe_binary(name)
        report["ocr_binaries"][name] = {
            "ok": ok, "detail": detail, "purpose": purpose, "install": how,
        }

    for name, pip_name, purpose in OPTIONAL_MODULES:
        ok, detail = _probe_module(name)
        report["optional_modules"][name] = {
            "ok": ok, "detail": detail, "purpose": purpose, "install": pip_name,
        }

    for name, purpose, how in OPTIONAL_BINARIES:
        ok, detail = _probe_binary(name)
        report["optional_binaries"][name] = {
            "ok": ok, "detail": detail, "purpose": purpose, "install": how,
        }

    missing_core = [n for n, v in report["core_modules"].items() if not v["ok"]]
    missing_ocr = [n for n, v in report["ocr_modules"].items() if not v["ok"]]
    missing_ocr += [n for n, v in report["ocr_binaries"].items() if not v["ok"]]

    report["missing_core"] = missing_core
    report["missing_ocr"] = missing_ocr
    # Reading a text/table PDF needs only the Python packages.
    report["ready"] = not missing_core
    # Reading a scanned PDF additionally needs the OCR binaries.
    report["ocr_ready"] = not missing_core and not missing_ocr
    return report


def main() -> int:
    report = collect()

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 1

    tick = lambda ok: "ok  " if ok else "MISS"  # noqa: E731

    print(f"EPF OCR extractor preflight   (python {report['python']})")
    print("-" * 64)

    print("Required Python packages")
    for name, v in report["core_modules"].items():
        extra = f"  {v['detail']}" if v["detail"] else ""
        print(f"  [{tick(v['ok'])}] {name:<12}{extra}")
        if not v["ok"]:
            print(f"         -> pip install {v['install']}")

    print("\nFor SCANNED PDFs only — pip install \"epf-reader[ocr]\"")
    for name, v in report["ocr_modules"].items():
        extra = f"  {v['detail']}" if v["detail"] else ""
        print(f"  [{tick(v['ok'])}] {name:<12}{extra}")

    print("\nFor SCANNED PDFs only — system binaries")
    for name, v in report["ocr_binaries"].items():
        print(f"  [{tick(v['ok'])}] {name:<12}  {v['detail'] or v['purpose']}")
        if not v["ok"]:
            print(f"         -> {v['install']}   ({v['purpose']})")

    print("\nOptional (the pipeline falls back without these)")
    for group in ("optional_modules", "optional_binaries"):
        for name, v in report[group].items():
            print(f"  [{tick(v['ok'])}] {name:<12}  {v['purpose']}")
            if not v["ok"]:
                hint = v["install"]
                prefix = "pip install " if group == "optional_modules" else ""
                print(f"         -> {prefix}{hint}")

    print("-" * 64)
    if not report["ready"]:
        print(f"NOT READY — missing Python packages: {', '.join(report['missing_core'])}")
        print('Install with:  pip install epf-reader   (or ./setup.sh)')
        return 1

    if report["ocr_ready"]:
        print("READY — text PDFs and scanned PDFs (OCR) are both supported.")
    else:
        print("READY for text/table PDFs — pdfplumber needs nothing further.")
        print(
            f"  Scanned passbooks would also need: {', '.join(report['missing_ocr'])}"
        )
        print("  Install those only if your passbook has no selectable text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
