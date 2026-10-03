# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""Tests for the importable reader API.

The PDF-dependent stages (``analyze_pdf``, ``extract_tables``) are patched with
a synthetic passbook table; everything downstream — cleaning, merging, parsing,
verification, validation, redaction — is the real code. That way these run with
no PDF, no Tesseract and no Java, while still catching a drift between
``epf_reader``'s glue and the pipeline's actual signatures.

    python3 -m unittest discover -s epf_ocr_extractor/tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from epf_reader import EPFReadError, read_epf_passbook
from epf_reader import reader as epf_reader

# A 6-column passbook table: Date, Particulars, Employee, Employer, Pension, Total
SYNTHETIC_TABLE = pd.DataFrame(
    [
        ["Date", "Particulars", "Employee", "Employer", "Pension", "Total"],
        ["01/04/2023", "OPENING BALANCE", "10000.00", "8000.00", "", "18000.00"],
        ["15/05/2023", "CONT FOR MAY 2023", "1800.00", "550.00", "1250.00", "3600.00"],
        ["15/06/2023", "CONT FOR JUN 2023", "1800.00", "550.00", "1250.00", "3600.00"],
        ["31/03/2024", "INT FOR FY 2023-24", "900.00", "700.00", "", "1600.00"],
        ["31/03/2024", "CLOSING BALANCE", "14500.00", "9800.00", "", "24300.00"],
    ]
)

SYNTHETIC_HEADER = {
    "uan": "100123456789",
    "pf_account_number": "KN/BNG/0012345/000/1234567",
    "member_name": "TEST USER",
    "establishment_name": "TEST COMPANY PVT LTD",
}

ANALYSIS = {
    "is_text_based": True,
    "pages": 2,
    "method": "tabula",
    "header": SYNTHETIC_HEADER,
    "table_region": {},
}


class ReaderTestCase(unittest.TestCase):
    """Base that patches the PDF stages and gives each test a real file path."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pdf = Path(self._tmp.name) / "passbook.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 not really a pdf")
        self.addCleanup(self._tmp.cleanup)

    def read(self, tables=None, **kwargs):
        tables = [SYNTHETIC_TABLE] if tables is None else tables
        with patch.object(epf_reader, "analyze_pdf", return_value=dict(ANALYSIS)), patch.object(
            epf_reader, "extract_tables", return_value=tables
        ):
            return read_epf_passbook(self.pdf, **kwargs)


class TestReadEPFPassbook(ReaderTestCase):
    def test_parses_contributions_and_interest(self):
        res = self.read()
        self.assertEqual(len(res.transactions), 3)
        self.assertEqual(
            res.type_counts, {"CONTRIBUTION": 2, "INTEREST": 1}
        )

    def test_transactions_are_date_sorted(self):
        res = self.read()
        dates = pd.to_datetime(res.transactions["date"], format="%d/%m/%Y")
        self.assertTrue(dates.is_monotonic_increasing)

    def test_amounts_survive_as_numbers(self):
        res = self.read()
        totals = res.totals()
        # 1800 + 1800 employee contributions + 900 interest
        self.assertAlmostEqual(totals["employee_contribution"], 4500.0, places=2)
        self.assertAlmostEqual(totals["employer_contribution"], 1800.0, places=2)

    def test_analysis_metadata_is_carried_through(self):
        res = self.read()
        self.assertEqual(res.pages, 2)
        self.assertTrue(res.is_text_based)
        self.assertEqual(res.method_used, "tabula")

    def test_explicit_method_overrides_analysis_recommendation(self):
        res = self.read(method="ocr")
        self.assertEqual(res.method_used, "ocr")

    def test_pii_redacted_by_default(self):
        res = self.read()
        self.assertNotIn("100123456789", str(res.header.values()))
        self.assertNotIn("TEST USER", str(res.header.values()))

    def test_pii_preserved_when_opted_out(self):
        res = self.read(redact_pii=False)
        self.assertEqual(res.header["uan"], "100123456789")
        self.assertEqual(res.header["member_name"], "TEST USER")

    def test_validation_can_be_skipped(self):
        res = self.read(validate=False)
        self.assertEqual(res.errors, [])
        self.assertEqual(res.warnings, [])
        self.assertTrue(res.is_valid)

    def test_validation_populates_findings(self):
        res = self.read(validate=True)
        # Whatever the verdict, errors/warnings must be plain lists of strings.
        self.assertIsInstance(res.errors, list)
        self.assertIsInstance(res.warnings, list)
        for item in (*res.errors, *res.warnings):
            self.assertIsInstance(item, str)


class TestFailureModes(ReaderTestCase):
    def test_missing_file_raises(self):
        with self.assertRaises(EPFReadError):
            read_epf_passbook(Path(self._tmp.name) / "nope.pdf")

    def test_no_tables_raises(self):
        with self.assertRaises(EPFReadError) as ctx:
            self.read(tables=[])
        self.assertIn("No tables extracted", str(ctx.exception))

    def test_unparseable_tables_raise_rather_than_exit(self):
        junk = pd.DataFrame([["nothing", "useful", "here"]])
        with self.assertRaises(EPFReadError):
            self.read(tables=[junk])

    def test_bad_method_rejected(self):
        with self.assertRaises(ValueError):
            read_epf_passbook(self.pdf, method="telepathy")


class TestDoctor(unittest.TestCase):
    def test_collect_reports_every_requirement(self):
        from epf_reader.doctor import CORE_MODULES, OCR_BINARIES, collect

        report = collect()
        self.assertEqual(set(report["core_modules"]), {m for m, _ in CORE_MODULES})
        self.assertEqual(set(report["ocr_binaries"]), {b for b, _, _ in OCR_BINARIES})
        self.assertIsInstance(report["ready"], bool)
        self.assertIsInstance(report["ocr_ready"], bool)

    def test_text_pdf_readiness_does_not_depend_on_ocr_binaries(self):
        """A missing Tesseract must not mark a working text-PDF install unusable."""
        from epf_reader import doctor

        with patch.object(doctor, "_probe_binary", return_value=(False, "")):
            report = doctor.collect()

        self.assertTrue(report["ready"], "text PDFs need no system binaries")
        self.assertFalse(report["ocr_ready"])
        # missing_ocr covers both the OCR python packages and the binaries
        self.assertTrue(
            {b for b, _, _ in doctor.OCR_BINARIES}.issubset(set(report["missing_ocr"]))
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
