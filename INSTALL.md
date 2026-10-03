# Installation

For the common case, see the [README](README.md):

```bash
pip install epf-reader
```

This file covers the awkward cases: per-distro system packages, isolated
installs, and development setup.

## What is actually required

**Only pip packages**, for any passbook with a selectable text layer — which is
most of them. `pdfplumber` reads the embedded text directly.

System packages are needed **only** for:

| Package | Needed for |
|---|---|
| `tesseract`, `poppler` | scanned (image-only) passbooks — the `ocr` extra |
| Java runtime | the optional `tabula` backend |
| `ghostscript` | the optional `camelot` backend |

Check before installing anything:

```bash
epf-inspect passbook.pdf   # SCANNED on any page means you need the OCR stack
epf-doctor                 # what you have, what each missing piece enables
```

`epf-doctor` reports **ready** (text PDFs) and **ocr_ready** (scanned too)
separately. A pip-only install correctly reports ready.

## System packages, by platform

Only if `epf-inspect` says your passbook is scanned.

### macOS

```bash
brew install tesseract poppler
# optional backends
brew install ghostscript
brew install --cask temurin
```

### Debian / Ubuntu (and WSL)

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng poppler-utils
# optional backends
sudo apt-get install -y default-jre ghostscript
```

### Fedora / RHEL

```bash
sudo dnf install -y tesseract poppler-utils
# optional backends
sudo dnf install -y ghostscript java-latest-openjdk-headless
```

### Arch

```bash
sudo pacman -S tesseract tesseract-data-eng poppler
```

### Windows

Use WSL2 and follow the Debian/Ubuntu steps. The package itself is pure Python
and works on native Windows, but Tesseract and Poppler must then be installed
manually and placed on `PATH`.

## Isolated install

To get the commands without touching any project environment:

```bash
pipx install epf-reader
pipx install "epf-reader[ocr]"     # with scanned-PDF support
```

This also sidesteps the `externally-managed-environment` error that system
Python installs raise on Debian, Ubuntu and Homebrew Python.

## Virtual environment

```bash
python3 -m venv venv
source venv/bin/activate           # Windows: venv\Scripts\activate
pip install epf-reader
```

## From a clone

```bash
git clone https://github.com/spartha08/epf-reader && cd epf-reader
./setup.sh --all                   # venv + every extra + system packages
```

`./setup.sh --help` lists the options. It is only a convenience wrapper around
`python -m venv` and `pip install`; `pip install .` does the same without it.

## Development

```bash
git clone https://github.com/spartha08/epf-reader && cd epf-reader
python3 -m venv venv && source venv/bin/activate
pip install -e ".[ui,excel]"
python -m unittest discover -s tests -v
```

The test suite needs no Tesseract, Java or real passbook — the PDF-reading
stages run against synthetic fixtures in `tests/fixtures/`. Tests needing
Streamlit skip themselves if the `ui` extra is absent.

Layout: a `src/` layout, so the installed package is what gets tested rather
than the working directory.

```
src/epf_reader/
├── reader.py            read_epf_passbook() — the library API
├── cli.py               epf-extract
├── inspect_pdf.py       epf-inspect
├── doctor.py            epf-doctor
├── ui.py                epf-ui launcher
├── streamlit_page.py    the Streamlit page itself
├── pdf_analyzer.py      PDF type detection, header metadata
├── table_extractor.py   backends (pdfplumber/tabula/camelot/ocr), layout mapping
├── transaction_parser.py row → transaction, classification, dates
├── csv_exporter.py      CSV/Excel output, PII redaction
├── validator.py         validation rules
├── image_preprocessor.py OCR pre-processing (imported lazily)
└── config/*.yaml        regex patterns, transaction keywords
```

OCR imports are deliberately lazy: `table_extractor` pulls `pytesseract`,
`pdf2image` and `cv2` inside the OCR function, so the `ocr` extra stays
optional. Keep it that way — a module-level import there makes ~100MB of
dependencies mandatory for everyone.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `externally-managed-environment` | Use `pipx`, or a venv. |
| `TesseractNotFoundError` | `pip install "epf-reader[ocr]"` plus the system packages above. |
| pdf2image `Unable to get page count` | Poppler is missing. |
| `epf-extract: command not found` | The venv isn't active, or pip installed elsewhere — `python -m epf_reader.cli` also works. |
| `No module named 'epf_reader'` | Installed into a different interpreter than the one you are running. |

See the README's troubleshooting table for extraction problems (unsupported
layouts, balance mismatches).
