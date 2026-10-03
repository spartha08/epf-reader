# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""Smoke tests for the Streamlit page, via Streamlit's own AppTest harness.

These render the page headlessly — no browser, no server — with the reader
patched out, so they check the page's own wiring (widgets, metrics, download
buttons, error paths) rather than the extraction. Skipped automatically if
Streamlit is not installed in this environment.

    python3 -m unittest discover -s epf_ocr_extractor/tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

HERE = Path(__file__).resolve().parent

try:
    from streamlit.testing.v1 import AppTest

    HAVE_STREAMLIT = True
except Exception:
    HAVE_STREAMLIT = False

import epf_reader

PAGE = Path(epf_reader.__file__).resolve().parent / "streamlit_page.py"
PDF_UPLOAD = [("passbook.pdf", b"%PDF-1.4 stand-in", "application/pdf")]


def _fake_result():
    from epf_reader import EPFResult

    return EPFResult(
        transactions=pd.DataFrame(
            [
                {
                    "date": "15/05/2023",
                    "particulars": "CONT FOR MAY 2023",
                    "transaction_type": "CONTRIBUTION",
                    "employee_contribution": 1800.0,
                    "employer_contribution": 550.0,
                    "notes": "",
                },
                {
                    "date": "31/03/2024",
                    "particulars": "INT FOR FY 2023-24",
                    "transaction_type": "INTEREST",
                    "employee_contribution": 900.0,
                    "employer_contribution": 700.0,
                    "notes": "",
                },
            ]
        ),
        header={"uan": "XXXXXXXX6789", "member_name": "XXXXXXX"},
        opening_balance={"date": "01/04/2023", "employee": 10000.0, "employer": 8000.0},
        closing_balance={"date": "31/03/2024", "employee": 14500.0, "employer": 9800.0},
        method_used="tabula",
        pages=2,
        is_text_based=True,
        is_valid=True,
        errors=[],
        warnings=[],
    )


@unittest.skipUnless(HAVE_STREAMLIT, "streamlit not installed")
class TestPageRenders(unittest.TestCase):
    def setUp(self) -> None:
        """Clear Streamlit's caches between runs.

        ``@st.cache_data`` is process-global, and every test here uploads the
        same stand-in bytes with the same settings — so without this the second
        test onwards gets the first test's cached result and the patched reader
        is never called.
        """
        import streamlit as st

        st.cache_data.clear()

    def test_renders_without_upload(self):
        at = AppTest.from_file(str(PAGE), default_timeout=120)
        at.run()
        self.assertFalse(at.exception, f"page raised: {[e.value for e in at.exception]}")
        self.assertIn("EPF Passbook Reader", [t.value for t in at.title])
        self.assertEqual(len(at.get("file_uploader")), 1)
        self.assertEqual(
            at.selectbox[0].options,
            ["auto", "pdfplumber", "ocr", "tabula", "camelot"],
        )

    def test_renders_results_after_upload(self):
        from epf_reader import reader as epf_reader

        at = AppTest.from_file(str(PAGE), default_timeout=120)
        with patch.object(epf_reader, "read_epf_passbook", return_value=_fake_result()):
            at.run()
            at.get("file_uploader")[0].set_value(PDF_UPLOAD)
            at.run()

        self.assertFalse(at.exception, f"page raised: {[e.value for e in at.exception]}")
        metrics = {m.label: m.value for m in at.metric}
        self.assertEqual(metrics["Transactions"], "2")
        self.assertEqual(metrics["Method"], "tabula")
        labels = [b.label for b in at.get("download_button")]
        self.assertIn("Download transactions CSV", labels)
        self.assertIn("Download metadata CSV", labels)

    def test_read_failure_surfaces_as_error_not_traceback(self):
        from epf_reader import reader as epf_reader

        at = AppTest.from_file(str(PAGE), default_timeout=120)
        with patch.object(
            epf_reader,
            "read_epf_passbook",
            side_effect=epf_reader.EPFReadError("no tables here"),
        ):
            at.run()
            at.get("file_uploader")[0].set_value(PDF_UPLOAD)
            at.run()

        self.assertFalse(at.exception)
        self.assertTrue(
            any("no tables here" in e.value for e in at.error),
            f"expected the read error surfaced; got {[e.value for e in at.error]}",
        )

    def test_balance_mismatch_shows_a_blocking_banner(self):
        """A balance break must be an error above the table, not a cell in it."""
        from epf_reader import reader as epf_reader

        bad = _fake_result()
        bad.balance_check = epf_reader.BalanceCheck(
            checked=True,
            employee_calculated=32440.0,
            employee_expected=32440.0,
            employer_calculated=15820.0,
            employer_expected=16220.0,
        )
        bad.balance_check.ok = False

        at = AppTest.from_file(str(PAGE), default_timeout=120)
        with patch.object(epf_reader, "read_epf_passbook", return_value=bad):
            at.run()
            at.get("file_uploader")[0].set_value(PDF_UPLOAD)
            at.run()

        self.assertFalse(at.exception)
        errors = " ".join(e.value for e in at.error)
        self.assertIn("Balance mismatch", errors)
        self.assertNotIn(
            "balances reconcile", " ".join(s.value for s in at.success)
        )

    def test_clean_read_reports_reconciled_balances(self):
        from epf_reader import reader as epf_reader

        good = _fake_result()
        good.balance_check = epf_reader.BalanceCheck(
            checked=True,
            employee_calculated=32440.0,
            employee_expected=32440.0,
            employer_calculated=15820.0,
            employer_expected=15820.0,
        )

        at = AppTest.from_file(str(PAGE), default_timeout=120)
        with patch.object(epf_reader, "read_epf_passbook", return_value=good):
            at.run()
            at.get("file_uploader")[0].set_value(PDF_UPLOAD)
            at.run()

        self.assertFalse(at.exception)
        self.assertTrue(
            any("balances reconcile" in s.value for s in at.success),
            f"got: {[s.value for s in at.success]}",
        )

    def test_no_deprecated_kwargs(self):
        """use_container_width is removed in current Streamlit; don't reintroduce it."""
        self.assertNotIn("use_container_width", PAGE.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
