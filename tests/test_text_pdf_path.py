# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""End-to-end tests over a real text-based PDF.

These read the synthetic passbooks in ``fixtures/`` with the actual pdfplumber
code path — no stubbing — so they cover what the stubbed tests in
``test_epf_reader.py`` cannot: that a text/table PDF is read correctly without
Tesseract, Java or Ghostscript.

    python3 -m unittest discover -s epf_ocr_extractor/tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

from epf_reader import table_extractor
from epf_reader import read_epf_passbook  # noqa: E402

CLEAN = FIXTURES / "passbook_clean.pdf"
MISMATCH = FIXTURES / "passbook_mismatch.pdf"
WITHDRAWAL = FIXTURES / "passbook_withdrawal.pdf"


class NoOptionalBackends(unittest.TestCase):
    """Force the core-only install: no tabula, no camelot, no OCR.

    Without this the tests could pass via a backend a fresh install would not
    have, which is exactly the regression being guarded against.
    """

    def setUp(self) -> None:
        self._tabula = table_extractor.TABULA_AVAILABLE
        self._camelot = table_extractor.CAMELOT_AVAILABLE
        table_extractor.TABULA_AVAILABLE = False
        table_extractor.CAMELOT_AVAILABLE = False

    def tearDown(self) -> None:
        table_extractor.TABULA_AVAILABLE = self._tabula
        table_extractor.CAMELOT_AVAILABLE = self._camelot


class TestTextPDFExtraction(NoOptionalBackends):
    def test_auto_picks_pdfplumber_for_a_text_pdf(self):
        res = read_epf_passbook(CLEAN)
        self.assertEqual(res.method_used, "pdfplumber")
        self.assertTrue(res.is_text_based)

    def test_all_transactions_recovered(self):
        res = read_epf_passbook(CLEAN)
        # 11 monthly contributions + 1 interest row; the opening, closing and
        # header rows are metadata, not transactions.
        self.assertEqual(len(res.transactions), 12)
        self.assertEqual(res.type_counts, {"CONTRIBUTION": 11, "INTEREST": 1})

    def test_amounts_parsed_exactly(self):
        res = read_epf_passbook(CLEAN)
        totals = res.totals()
        self.assertAlmostEqual(totals["employee_contribution"], 22440.0, places=2)
        self.assertAlmostEqual(totals["employer_contribution"], 7820.0, places=2)

    def test_dates_in_order_and_well_formed(self):
        res = read_epf_passbook(CLEAN)
        dates = pd.to_datetime(res.transactions["date"], format="%d/%m/%Y")
        self.assertFalse(dates.isna().any())
        self.assertTrue(dates.is_monotonic_increasing)

    def test_explicit_pdfplumber_method_matches_auto(self):
        self.assertTrue(
            read_epf_passbook(CLEAN, method="pdfplumber").transactions.equals(
                read_epf_passbook(CLEAN).transactions
            )
        )


class TestPDFAnalysis(NoOptionalBackends):
    """Covers the pypdf-backed page count and the text/scanned verdict.

    get_page_count() had no direct test, so swapping its backend (PyPDF2 is
    end-of-life) would otherwise have been unverified by the suite.
    """

    def test_page_count(self):
        from epf_reader.pdf_analyzer import get_page_count

        for name in ("passbook_clean.pdf", "passbook_mismatch.pdf", "passbook_9col.pdf"):
            with self.subTest(pdf=name):
                self.assertEqual(get_page_count(str(FIXTURES / name)), 1)

    def test_page_count_on_a_non_pdf_returns_zero(self):
        from epf_reader.pdf_analyzer import get_page_count

        self.assertEqual(get_page_count(str(FIXTURES / "passbook.tex")), 0)

    def test_analysis_reports_pages_and_text_verdict(self):
        res = read_epf_passbook(CLEAN)
        self.assertEqual(res.pages, 1)
        self.assertTrue(res.is_text_based)


class TestBalanceExtraction(NoOptionalBackends):
    """The balance rows label themselves in the particulars column, not column 0."""

    def test_opening_balance_found(self):
        res = read_epf_passbook(CLEAN)
        self.assertEqual(res.opening_balance["date"], "01/04/2023")
        self.assertAlmostEqual(res.opening_balance["employee"], 10000.0, places=2)
        self.assertAlmostEqual(res.opening_balance["employer"], 8000.0, places=2)

    def test_closing_balance_found(self):
        res = read_epf_passbook(CLEAN)
        self.assertEqual(res.closing_balance["date"], "31/03/2024")
        self.assertAlmostEqual(res.closing_balance["employee"], 32440.0, places=2)

    def test_amounts_without_thousands_commas_are_parsed(self):
        """The old extractor required a comma, so sub-1000 amounts were skipped."""
        row = pd.DataFrame([["15/05/2023", "OPENING BALANCE", "550.00", "99.50"]])
        got = table_extractor.extract_opening_balance(row)
        self.assertAlmostEqual(got["employee"], 550.0, places=2)
        self.assertAlmostEqual(got["employer"], 99.5, places=2)

    def test_date_cell_is_not_read_as_an_amount(self):
        row = pd.DataFrame([["01/04/2023", "OPENING BALANCE", "1,000.00", "2,000.00"]])
        got = table_extractor.extract_opening_balance(row)
        self.assertAlmostEqual(got["employee"], 1000.0, places=2)
        self.assertEqual(got["date"], "01/04/2023")

    def test_legacy_ob_int_layout_still_works(self):
        """The original 'OB Int. Updated upto <date>' layout must not regress."""
        row = pd.DataFrame(
            [["OB Int. Updated upto 31/03/2023", "", "12,345.00", "6,789.00"]]
        )
        got = table_extractor.extract_opening_balance(row)
        self.assertEqual(got["date"], "31/03/2023")
        self.assertAlmostEqual(got["employee"], 12345.0, places=2)

    def test_missing_balance_rows_return_zeros(self):
        row = pd.DataFrame([["15/05/2023", "CONT FOR MAY 2023", "1,800.00", "550.00"]])
        self.assertEqual(
            table_extractor.extract_opening_balance(row),
            {"date": "", "employee": 0, "employer": 0},
        )


class TestBalanceReconciliation(NoOptionalBackends):
    def test_clean_passbook_reconciles(self):
        check = read_epf_passbook(CLEAN).balance_check
        self.assertTrue(check.checked)
        self.assertTrue(check.ok)
        self.assertEqual(check.describe(), [])

    def test_mismatch_is_detected_and_quantified(self):
        check = read_epf_passbook(MISMATCH).balance_check
        self.assertTrue(check.checked)
        self.assertFalse(check.ok)
        self.assertAlmostEqual(check.employer_diff, 400.0, places=2)
        self.assertEqual(len(check.describe()), 1)
        self.assertIn("400.00", check.describe()[0])

    def test_employee_side_reconciles_even_when_employer_does_not(self):
        check = read_epf_passbook(MISMATCH).balance_check
        self.assertLess(check.employee_diff, 0.01)

    def test_unchecked_when_no_balances_printed(self):
        from epf_reader.reader import _check_balances

        check = _check_balances([{"employee_contribution": 1.0,
                                  "employer_contribution": 1.0}], {}, {})
        self.assertFalse(check.checked)
        # "unknown" must not be reported as a pass
        self.assertEqual(check.describe(), [])


class TestWithdrawalDirectionEndToEnd(NoOptionalBackends):
    """A real PDF carrying a DR withdrawal, proven by its own printed balances.

    The fixture's closing balance only follows from the rows if the withdrawal
    is subtracted: 50,000 + 2,400 + 2,400 - 10,000 = 44,800. Taking the DR row
    as printed gives 64,800, so the reconciliation is independent evidence that
    the sign is applied, not merely an assertion restating the code.
    """

    def test_withdrawal_is_negative(self):
        res = read_epf_passbook(WITHDRAWAL)
        debits = res.transactions[res.transactions["direction"] == "DR"]
        self.assertEqual(len(debits), 1)
        self.assertAlmostEqual(debits.iloc[0]["employee_contribution"], -10000.0, places=2)
        self.assertAlmostEqual(debits.iloc[0]["employer_contribution"], -8000.0, places=2)

    def test_balances_reconcile_only_with_the_sign_applied(self):
        res = read_epf_passbook(WITHDRAWAL)
        check = res.balance_check
        self.assertTrue(check.checked, "the fixture prints opening and closing balances")
        self.assertTrue(check.ok, f"did not reconcile: {check.describe()}")
        self.assertAlmostEqual(check.employee_calculated, 44800.0, places=2)
        self.assertAlmostEqual(check.employer_calculated, 34300.0, places=2)

    def test_unsigned_reading_would_not_reconcile(self):
        """Guards the regression directly: had the sign been dropped, the
        employee side would land on 64,800 against a printed 44,800."""
        res = read_epf_passbook(WITHDRAWAL)
        unsigned = res.opening_balance["employee"] + sum(
            abs(v) for v in res.transactions["employee_contribution"]
        )
        self.assertAlmostEqual(unsigned, 64800.0, places=2)
        self.assertNotAlmostEqual(unsigned, res.closing_balance["employee"], places=2)

    def test_contributions_stay_positive(self):
        res = read_epf_passbook(WITHDRAWAL)
        credits = res.transactions[res.transactions["direction"] == "CR"]
        self.assertEqual(len(credits), 2)
        self.assertTrue((credits["employee_contribution"] > 0).all())


class TestRedactionCoversEveryPIIField(NoOptionalBackends):
    def test_pf_account_number_is_redacted(self):
        """Regression: the field list said 'pf_account', the key is
        'pf_account_number', so it leaked."""
        res = read_epf_passbook(CLEAN)
        self.assertEqual(res.header["pf_account_number"], "REDACTED")

    def test_every_identifying_field_is_redacted(self):
        res = read_epf_passbook(CLEAN)
        for value in res.header.values():
            if value:
                self.assertEqual(value, "REDACTED", f"unredacted value: {value!r}")

    def test_raw_values_available_when_opted_out(self):
        res = read_epf_passbook(CLEAN, redact_pii=False)
        self.assertEqual(res.header["uan"], "100123456789")
        self.assertEqual(res.header["pf_account_number"], "KN/BNG/0012345/000/1234567")

    def test_header_field_list_matches_the_analyzer(self):
        """Every header key the analyzer can emit must be classified as PII or
        not — otherwise a newly added field silently leaks."""
        from epf_reader.csv_exporter import NON_PII_HEADER_FIELDS, PII_HEADER_FIELDS

        res = read_epf_passbook(CLEAN, redact_pii=False)
        classified = set(PII_HEADER_FIELDS) | set(NON_PII_HEADER_FIELDS)
        unclassified = set(res.header) - classified
        self.assertEqual(unclassified, set(), f"unclassified header fields: {unclassified}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
