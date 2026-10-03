# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""Tests for the 9-column passbook layout.

Two different real layouts both have nine columns, so the mapping cannot be
chosen by column count:

  "split"    wage month and date in their own columns — what pdfplumber's
             rect-based extraction yields:
             ['Mar-2015', '01-04-2015', 'CR', 'Cont. For ...', '20,000',
              '15,000', '2,400', '1,150', '1,250']
  "combined" a leading empty column and wage month + date in one cell — what
             tabula yielded:
             ['', 'Mar-2015 01-04-2015', 'CR', 'Cont. For ...', ...]

Reading a split table with the combined mapping leaves every date NaN and drops
every row, so both shapes are covered here.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

from epf_reader import table_extractor as te
from epf_reader import read_epf_passbook  # noqa: E402
from epf_reader.transaction_parser import parse_transactions

NINE_COL_PDF = HERE / "fixtures" / "passbook_9col.pdf"

HEADER = [
    "Wage Month", "Transaction Date", "Transaction Type", "Particulars",
    "EPF Wages", "EPS Wages", "Employee Share", "Employer Share", "Pension Share",
]
# Self-consistent statutory-ceiling figures (no real passbook data):
#   EPF wages 20,000 x 12%   = 2,400  (employee)
#   EPS wages 15,000 x 8.33% = 1,250  (pension, post-Sept-2014 ceiling)
#   2,400 - 1,250            = 1,150  (employer = total less pension)
SPLIT_ROW = ["Mar-2015", "01-04-2015", "CR", "Cont. For Due-Month 042015",
             "20,000", "15,000", "2,400", "1,150", "1,250"]
COMBINED_ROW = ["", "Mar-2015 01-04-2015", "CR", "Cont. For Due-Month 042015",
                "20,000", "15,000", "2,400", "1,150", "1,250"]
INTEREST_ROW = ["", "31-03-2016", "CR", "Int. Updated upto 31/03/2016",
                "", "", "1,340", "1,100", "0"]
DEBIT_ROW = ["", "15-06-2016", "DR", "PF Withdrawal", "", "", "2,000", "1,500", "0"]


def _parse(rows):
    cleaned, meta = te.clean_extracted_tables([pd.DataFrame(rows)])
    if not cleaned:
        return [], meta
    merged = te.merge_multi_page_tables(cleaned)
    return parse_transactions(merged), meta


class TestVariantDetection(unittest.TestCase):
    def test_split_layout_detected(self):
        df = pd.DataFrame([HEADER, SPLIT_ROW, SPLIT_ROW])
        self.assertEqual(te._detect_9col_variant(df), "split")

    def test_combined_layout_detected(self):
        df = pd.DataFrame([HEADER, COMBINED_ROW, COMBINED_ROW])
        self.assertEqual(te._detect_9col_variant(df), "combined")

    def test_decided_by_majority_not_by_first_row(self):
        """One odd row must not flip the mapping for the whole table."""
        df = pd.DataFrame([INTEREST_ROW, SPLIT_ROW, SPLIT_ROW, SPLIT_ROW])
        self.assertEqual(te._detect_9col_variant(df), "split")


class TestSplitLayoutParsing(unittest.TestCase):
    def test_columns_mapped_to_the_right_fields(self):
        txns, _ = _parse([HEADER, SPLIT_ROW])
        self.assertEqual(len(txns), 1)
        txn = txns[0]
        self.assertEqual(txn["date"], "01/04/2015")
        self.assertEqual(txn["transaction_type"], "CONTRIBUTION")
        # employee/employer must come from cols 6/7, not the wage columns 4/5
        self.assertAlmostEqual(txn["employee_contribution"], 2400.0, places=2)
        self.assertAlmostEqual(txn["employer_contribution"], 1150.0, places=2)

    def test_epf_wages_are_not_mistaken_for_contributions(self):
        txns, _ = _parse([HEADER, SPLIT_ROW])
        for value in (20000.0, 15000.0):
            self.assertNotIn(
                value,
                (txns[0]["employee_contribution"], txns[0]["employer_contribution"]),
            )

    def test_header_row_is_dropped(self):
        txns, _ = _parse([HEADER, SPLIT_ROW])
        self.assertEqual(len(txns), 1)

    def test_debit_rows_are_parsed_and_flagged(self):
        txns, _ = _parse([HEADER, SPLIT_ROW, DEBIT_ROW])
        kinds = {t["transaction_type"] for t in txns}
        self.assertIn("WITHDRAWAL", kinds)


class TestInterestRowSurvives(unittest.TestCase):
    """Regression: the header filter matched 'DATE' as a substring, so
    "Int. UpDATEd upto ..." was deleted — losing the annual interest credit."""

    def test_interest_row_is_kept(self):
        txns, _ = _parse([HEADER, SPLIT_ROW, INTEREST_ROW])
        kinds = [t["transaction_type"] for t in txns]
        self.assertIn("INTEREST", kinds)
        self.assertEqual(len(txns), 2)

    def test_interest_is_not_double_counted(self):
        """It must come from the table or the metadata, never both."""
        txns, meta = _parse([HEADER, SPLIT_ROW, INTEREST_ROW])
        from_table = sum(t["transaction_type"] == "INTEREST" for t in txns)
        self.assertEqual(from_table, 1)
        self.assertEqual(meta["interest_rows"], [])

    def test_header_filter_matches_words_not_substrings(self):
        self.assertTrue(te._looks_like_header_row("Wage Month Transaction Date"))
        self.assertTrue(te._looks_like_header_row("OPENING BALANCE"))
        self.assertFalse(te._looks_like_header_row("Int. Updated upto 31/03/2016"))
        self.assertFalse(te._looks_like_header_row("Cont. For Due-Month 042015"))


class TestCommalessAmounts(unittest.TestCase):
    """Real passbooks print whole rupees, so a sub-1000 figure such as '705'
    carries neither a thousands comma nor a decimal part. The extractor used to
    require one of the two and skipped these entirely."""

    def test_bare_integer_cell_is_read_as_an_amount(self):
        row = pd.DataFrame([["", "OPENING BALANCE", "705", "980"]])
        got = te.extract_opening_balance(row)
        self.assertAlmostEqual(got["employee"], 705.0, places=2)
        self.assertAlmostEqual(got["employer"], 980.0, places=2)

    def test_date_is_still_not_read_as_an_amount(self):
        row = pd.DataFrame([["01-04-2015", "OPENING BALANCE", "20,000", "15,000"]])
        got = te.extract_opening_balance(row)
        self.assertAlmostEqual(got["employee"], 20000.0, places=2)

    def test_wage_month_is_not_read_as_an_amount(self):
        row = pd.DataFrame([["Mar-2015", "OPENING BALANCE", "1,000", "2,000"]])
        got = te.extract_opening_balance(row)
        self.assertAlmostEqual(got["employee"], 1000.0, places=2)


class TestNineColumnPDFEndToEnd(unittest.TestCase):
    """The whole pipeline over a real 9-column text PDF, no optional backends."""

    def setUp(self) -> None:
        self._t, self._c = te.TABULA_AVAILABLE, te.CAMELOT_AVAILABLE
        te.TABULA_AVAILABLE = te.CAMELOT_AVAILABLE = False

    def tearDown(self) -> None:
        te.TABULA_AVAILABLE, te.CAMELOT_AVAILABLE = self._t, self._c

    def test_reads_every_row(self):
        res = read_epf_passbook(NINE_COL_PDF)
        self.assertEqual(res.method_used, "pdfplumber")
        self.assertEqual(len(res.transactions), 5)
        self.assertEqual(res.type_counts, {"CONTRIBUTION": 4, "INTEREST": 1})

    def test_amounts_are_the_contribution_columns(self):
        res = read_epf_passbook(NINE_COL_PDF)
        totals = res.totals()
        # 4 x 2,400 employee + 1,340 interest
        self.assertAlmostEqual(totals["employee_contribution"], 10940.0, places=2)
        # 4 x 1,150 employer + 1,100 interest
        self.assertAlmostEqual(totals["employer_contribution"], 5700.0, places=2)

    def test_no_printed_balances_reads_as_unknown_not_ok(self):
        """This layout prints no opening/closing row, so there is no safety net —
        that must be reported as unchecked rather than as a pass."""
        res = read_epf_passbook(NINE_COL_PDF)
        self.assertFalse(res.balance_check.checked)


if __name__ == "__main__":
    unittest.main(verbosity=2)
