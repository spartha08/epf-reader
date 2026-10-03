# Test fixtures

Synthetic passbooks, generated from `passbook.tex` with `pdflatex`. They contain
**no real data** — placeholder UAN `100123456789`, `TEST USER`,
`TEST COMPANY PVT LTD` — and exist so the text-PDF extraction path is tested
against a real PDF rather than a stubbed table.

| File | Purpose |
|---|---|
| `passbook_clean.pdf` | Opening + transactions reconcile to the closing balance. |
| `passbook_mismatch.pdf` | Employer closing balance is ₹400 off — exercises the balance-break detection. |
| `passbook_9col.pdf` | The 9-column "split" layout a real EPFO passbook uses: `Wage Month, Transaction Date, CR/DR, Particulars, EPF Wages, EPS Wages, Employee Share, Employer Share, Pension Share`. No opening/closing row, so the balance check reads as *unchecked*. |
| `passbook.tex` / `passbook9.tex` | Sources. Regenerate: `pdflatex passbook.tex` |

Both are text-based (selectable text, ruled table), which is the layout the
`pdfplumber` path handles.

Note: `pdflatex` draws the grid with stroked lines, where a real EPFO passbook
draws filled rectangles. pdfplumber builds `page.edges` from both, so the
ruled-grid strategy behaves the same either way. The LaTeX PDFs also extract
some cells without inter-word spaces (`Cont. ForDue-Month042015`) — a glyph
spacing artifact of the fixtures, not of real passbooks.
