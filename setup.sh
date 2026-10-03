#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
#
# Convenience installer. Equivalent to a venv plus `pip install`, with the
# system packages pip cannot provide. macOS and Linux.
#
#   ./setup.sh                  venv + core install (text PDFs; no system packages)
#   ./setup.sh --ocr            also scanned-PDF support (Tesseract + Poppler)
#   ./setup.sh --ui             also the epf-ui Streamlit page
#   ./setup.sh --all            core + ocr + ui + excel
#   ./setup.sh --venv PATH      install into that environment instead of ./venv
#   ./setup.sh --editable       install in editable mode (for development)
#
# Plain `pip install .` works too — this script only adds the venv and the
# Tesseract/Poppler step.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV=""
EXTRAS=""
WITH_OCR=0
EDITABLE=""

add_extra() { EXTRAS="${EXTRAS:+$EXTRAS,}$1"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ocr)      add_extra ocr; WITH_OCR=1; shift ;;
    --ui)       add_extra ui; shift ;;
    --excel)    add_extra excel; shift ;;
    --backends) add_extra backends; shift ;;
    --all)      add_extra ocr; add_extra ui; add_extra excel; WITH_OCR=1; shift ;;
    --venv)     VENV="${2:?--venv needs a path}"; shift 2 ;;
    --editable|-e) EDITABLE="-e"; shift ;;
    -h|--help)  sed -n '4,$p' "${BASH_SOURCE[0]}" | sed -n '/^#/!q;p' | sed 's/^#\( \|$\)//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }

# --------------------------------------------------------------------------
# Tesseract and Poppler are for SCANNED passbooks only. A PDF with a text layer
# is read by pdfplumber, a plain pip package — so a missing package manager is a
# warning here, never a failure.
if [[ $WITH_OCR -eq 1 ]]; then
  say "Installing OCR system dependencies (tesseract, poppler)"
  if command -v tesseract >/dev/null 2>&1 && command -v pdftoppm >/dev/null 2>&1; then
    echo "    already present"
  elif command -v brew >/dev/null 2>&1; then
    brew install tesseract poppler
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y tesseract-ocr tesseract-ocr-eng poppler-utils
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y tesseract poppler-utils
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm tesseract tesseract-data-eng poppler
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y tesseract-ocr poppler-tools
  else
    warn "No supported package manager found — install Tesseract and Poppler yourself."
    warn "Text/table PDFs work without them."
  fi
fi

# --------------------------------------------------------------------------
say "Setting up the Python environment"
if [[ -z "$VENV" ]]; then
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    VENV="$VIRTUAL_ENV"
    echo "    using the activated venv: $VENV"
  else
    VENV="$HERE/venv"
    echo "    using $VENV"
  fi
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }
  python3 -m venv "$VENV"
fi
PY="$VENV/bin/python"
echo "    python: $("$PY" --version)"

say "Installing epf-reader${EXTRAS:+[$EXTRAS]}"
"$PY" -m pip install --quiet --upgrade pip
if [[ -n "$EXTRAS" ]]; then
  "$PY" -m pip install $EDITABLE "$HERE[$EXTRAS]"
else
  "$PY" -m pip install $EDITABLE "$HERE"
fi

# --------------------------------------------------------------------------
say "Preflight"
set +e
"$VENV/bin/epf-doctor"
STATUS=$?
set -e
[[ $STATUS -ne 0 ]] && { warn "Required packages are still missing — see above."; exit $STATUS; }

cat <<MSG

Done. The commands are on $VENV/bin — activate the venv to use them directly:

  source $VENV/bin/activate

  epf-inspect passbook.pdf                        # text or scanned?
  epf-extract --input passbook.pdf --output-dir out/
  epf-doctor                                      # what is installed
  epf-ui                                          # web page (needs --ui)

MSG
