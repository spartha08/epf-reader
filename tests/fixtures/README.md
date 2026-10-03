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
| `passbook_withdrawal.pdf` | 9-column layout with a **DR withdrawal** and printed opening/closing balances. The closing figure only follows if the debit is subtracted (50,000 + 2,400 + 2,400 − 10,000 = 44,800), so the reconciliation independently proves the sign is applied. |
| `passbook*.tex` | Sources. Regenerate: `pdflatex passbook.tex` |

Both are text-based (selectable text, ruled table), which is the layout the
`pdfplumber` path handles.

Note: `pdflatex` draws the grid with stroked lines, where a real EPFO passbook
draws filled rectangles. pdfplumber builds `page.edges` from both, so the
ruled-grid strategy behaves the same either way. The LaTeX PDFs also extract
some cells without inter-word spaces (`Cont. ForDue-Month042015`) — a glyph
spacing artifact of the fixtures, not of real passbooks. Where a space matters
to what is being tested, the `.tex` uses an explicit `\hspace` so the gap is
wide enough to extract: without it `OPENING BALANCE` comes out as
`OPENINGBALANCE`, the header filter misses it, and the balance rows leak into
the transactions.
