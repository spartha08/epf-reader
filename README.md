# epf-reader

Extract transactions from an **EPFO member passbook PDF** (India's Employees'
Provident Fund) into CSV — contributions, interest credits, withdrawals and
transfers, with the amounts and dates as printed.

Runs entirely on your machine. Nothing is uploaded anywhere.

```
                    ┌─ text layer?  ─ yes ─▶ pdfplumber   (pip only, exact, fast)
  passbook.pdf ─────┤
                    └─ scanned?     ─ yes ─▶ Tesseract OCR (needs system packages)
```

## Install

```bash
pip install epf-reader
```

For a scanned (image-only) passbook, add the OCR extra and its two system
packages — see [Extras](#extras):

```bash
pip install "epf-reader[ocr]"
brew install tesseract poppler          # or: apt install tesseract-ocr poppler-utils
```

## Quick start

```bash
epf-inspect passbook.pdf                              # text or scanned?
epf-extract --input passbook.pdf --output-dir out/
```

That writes `out/epf_transactions.csv` plus metadata, a summary and a validation
report. **Personal details are redacted by default** — see [Privacy](#privacy).

| Command | Does |
|---|---|
| `epf-extract` | read a passbook into CSV |
| `epf-inspect` | report whether a PDF is text or scanned, and if its table is detectable |
| `epf-doctor` | report what is installed and what each missing piece is for |
| `epf-ui` | open the web page (needs the `ui` extra) |

## Extras

Core install reads any passbook with a text layer — which is most of them — and
pulls only `pdfplumber`, `pypdf`, `pandas`, `python-dateutil` and `PyYAML`.

| Extra | For | Also needs |
|---|---|---|
| `ocr` | scanned, image-only passbooks | Tesseract + Poppler binaries |
| `ui` | the `epf-ui` Streamlit page | — |
| `excel` | `--excel` output | — |
| `backends` | the `tabula` / `camelot` readers | Java / Ghostscript |
| `all` | `ocr` + `ui` + `excel` | as above |

```bash
pip install "epf-reader[all]"
```

`epf-doctor` tells you exactly what is present and what each absent piece
enables; it reports **ready** (text PDFs) and **ocr_ready** (scanned too)
separately, so a pip-only install isn't flagged as broken for lacking an OCR
engine it will never call.

## Most passbooks need no system packages

If your passbook has selectable text (open it in a PDF viewer and search for
`Cont` — if it highlights, it does), everything installs from pip. `pdfplumber`
reads the embedded text layer directly, which is faster and more accurate than
OCR because nothing is transcribed from pixels.

Not sure which you have:

```bash
epf-inspect passbook.pdf
```

```
 page    chars   words   lines   rects  verdict     rows(lines/text)
--------------------------------------------------------------------
    1     3141     452       0     148  TEXT        21/71

VERDICT: text-based on every page.
  -> pdfplumber or tabula will read it. OCR (Tesseract) is NOT needed.
```

`rows(lines/text)` is how many table rows each pdfplumber strategy recovers. A
double-digit count in either means the table is detectable. `TEXT` with `0/0`
means the text is present but not laid out as a table — a layout the parser
cannot see. It also accepts `--password` for an encrypted PDF.

## Check the result before you trust it

A passbook prints its own opening and closing balances, so an extraction can be
checked against the statement itself: if the rows in between don't account for
the difference, rows were dropped, duplicated or misread.

```
  Verification: Balance verification: OK
```

That line (also the last row's `notes` column in the CSV) is the thing to read.
`MISMATCH: …` means do not use the output. If your passbook prints no balances,
the check reports *unchecked* — which is "unknown", not "fine".

## Usage

### Command line

```bash
epf-extract --input passbook.pdf --output-dir out/

  --method {auto,pdfplumber,tabula,camelot,ocr}   default: auto
  --output NAME        base name for output files (default: epf_transactions)
  --no-redact-pii      keep UAN, PF account number, member name in the output
  --excel              also write .xlsx
  --debug              dump the raw extracted tables
  --no-validate        skip validation
```

Installing from a clone instead? `./setup.sh` makes a venv, installs the
package and runs the preflight in one step.

### Python

```python
from epf_reader import read_epf_passbook

res = read_epf_passbook("passbook.pdf")      # PII redacted by default

res.transactions        # pandas DataFrame
res.header              # UAN, PF account, establishment, …
res.opening_balance     # {'date', 'employee', 'employer'}
res.closing_balance
res.balance_check       # reconciliation — see below
res.errors, res.warnings
res.type_counts         # {'CONTRIBUTION': 12, 'INTEREST': 1}
res.totals()            # summed contribution columns
```

```python
check = res.balance_check
if check.checked and not check.ok:
    for line in check.describe():
        print(line)   # "Employer: transactions give ₹15,820.00, passbook says ₹16,220.00 …"
```

It raises `EPFReadError` rather than calling `sys.exit()`, so it is safe to drive
from a long-running process. `method=` forces a backend; `redact_pii=False`
returns raw identifiers.

### Web UI

```bash
pip install "epf-reader[ui]"
epf-ui
```

Upload a PDF; see the balances, validation findings and transactions, and
download CSVs. OCR results are cached on the uploaded bytes, so clicking around
doesn't re-run a slow extraction.

To embed it as a page in an existing Streamlit app, install the package into
that app's environment and symlink the page in:

```bash
/path/to/app/venv/bin/pip install "epf-reader[ui]"
ln -s "$(/path/to/app/venv/bin/python -c 'import epf_reader.streamlit_page as m; print(m.__file__)')" \
      /path/to/app/pages/5_EPF_Passbook.py
```

## Supported passbook layouts

EPFO passbooks are not one format. The parser maps a table by column count, and
for the 9-column case by inspecting the data, because **two different real
layouts both have nine columns**:

| Columns | Shape |
|---|---|
| 9 "split" | `Wage Month, Date, CR/DR, Particulars, EPF Wages, EPS Wages, Employee, Employer, Pension` |
| 9 "combined" | leading empty column, with wage month + date together in one cell |
| 12 | contributions plus running balances per column |
| 6 / 5 | `Date, Particulars, Employee, Employer[, Pension], Total` (5 = pre-2014, no pension) |

Reading a split table with the combined mapping yields `NaN` dates and drops
every row, which is why the variant is detected rather than assumed. An
unrecognised column count logs `WARNING: Unexpected column count: N` and
**discards that table** — it does not silently degrade.

If your passbook fails, the two lines that identify the layout are:

```bash
epf-extract --input passbook.pdf --output-dir out/ 2>&1 | grep DEBUG
```

## Withdrawals and direction

A passbook with a **CR/DR column** prints its amounts unsigned and carries the
direction there. Those layouts (both 9-column variants) are read with the sign
applied: a `DR` row — a withdrawal, a transfer out, TDS — comes back negative,
and the passbook's own marker is preserved in a `direction` column in the CSV
so a negative figure can be traced to the row that declared it a debit.

Signing uses `-abs()`, so a layout that already prints negatives is not flipped
back to positive.

Layouts **without** a CR/DR column (5, 6 and 12-column) carry no direction to
read, so their amounts are taken as printed. If a row there classifies as an
outflow while its amounts are positive, the extraction says so rather than
guessing a sign:

```
WARNING: row 7 classified WITHDRAWAL but this layout has no CR/DR column,
so its amounts are taken as printed.
```

Either way the balance reconciliation is the check that matters: if the signs
are wrong, opening + transactions will not equal the printed closing balance.

## Extraction backends

| Backend | Needs | When |
|---|---|---|
| `pdfplumber` | nothing (pip) | **Default for any PDF with a text layer.** |
| `ocr` | Tesseract + Poppler | Scanned pages only. Slowest, and can misread. |
| `tabula` | Java | Alternative text reader. Optional. |
| `camelot` | Ghostscript | Alternative for bordered tables. Optional. |

`auto` resolves to `pdfplumber` for a text PDF and `ocr` for a scanned one. If
`tabula` or `camelot` is requested but missing or failing, a text PDF falls back
to **pdfplumber, never to OCR** — dropping to pixel transcription for want of a
Java runtime would be a silent loss of accuracy.

```bash
pip install "epf-reader[backends]"
```

Note `camelot-py[cv]` depends on `opencv-python`, which conflicts with the
`opencv-python-headless` in the `ocr` extra. Install one or the other.

## Privacy

Redaction is **on by default** everywhere — library, CLI and UI. UAN, PF account
number, member name, father/husband name, establishment name and ID, date of
birth and dates of joining are masked in the transactions, the metadata and the
downloads. Pass `--no-redact-pii` (or `redact_pii=False`) to keep them.

Extraction and OCR are entirely local; the tool makes no network calls.

## Tests

```bash
git clone https://github.com/spartha08/epf-reader && cd epf-reader
pip install -e ".[ui,excel]"
python -m unittest discover -s tests -v
```

69 tests, no Tesseract or Java required. They cover the pdfplumber path
end-to-end against synthetic passbooks in `tests/fixtures/` — with
`tabula`/`camelot` forced off, so nothing passes via a backend a fresh install
lacks — plus layout detection, balance reconciliation, PII redaction and the
Streamlit page (via Streamlit's `AppTest`; skipped if Streamlit is absent).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `TesseractNotFoundError` | Only needed for scanned PDFs. `pip install "epf-reader[ocr]"` plus `brew install tesseract` / `apt install tesseract-ocr`. |
| pdf2image "Unable to get page count" | Poppler missing: `brew install poppler` / `apt install poppler-utils`. |
| "No tables extracted" | Run `epf-inspect`. `SCANNED` → `--method ocr`. `TEXT` with `0/0` rows → unsupported layout. |
| `WARNING: Unexpected column count: N` | Layout not mapped. Open an issue with the two `DEBUG` lines (they contain no personal details). |
| Contributions equal your monthly salary | The wage columns were read as contributions — wrong 9-column variant. Check `9-column layout detected as '…'`. |
| `MISMATCH` in the balance line | Rows dropped or misparsed. Try another `--method`; don't use the output as-is. |
| `java: command not found` | Harmless — a text PDF falls back to pdfplumber. |
| "externally-managed-environment" on pip | Install into a venv, or use `pipx install epf-reader`. |
| UI can't import the reader | The package is in a different environment than Streamlit. Install it into the one running Streamlit. |

See [INSTALL.md](INSTALL.md) for detailed installation notes.

## Requirements

Python 3.9+. Dependencies are declared with lower bounds, not exact pins, so pip
can resolve wheels matching your interpreter.

## License

[Apache License 2.0](LICENSE) — see [NOTICE](NOTICE) for attribution.

Apache-2.0 rather than MIT because it carries an express patent grant, explicit
contribution terms, and a thorough warranty disclaimer — worth having for a tool
that parses financial records people may act on.

Parts of this code were written with LLM assistance, directed and reviewed by
the author. There is no separate licence for machine-generated code; the
AI-specific licences that exist (OpenRAIL and similar) cover *model weights*,
not source. What differs is **copyrightability**, not licensing: the US
Copyright Office holds that material without human authorship is not
copyrightable, while India's Copyright Act s.2(d)(vi) names the author of a
computer-generated work as "the person who causes the work to be created". That
boundary is unsettled, so treat this section as a statement of intent, not legal
advice.
