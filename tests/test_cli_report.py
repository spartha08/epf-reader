# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""The CLI's machine-readable integrity signals.

A caller must be able to detect a balance mismatch programmatically, and that
signal must not disturb the CSV. So there are two channels, both tested here:

  * the process **exit code** — 3 for a mismatch, 4 for unchecked under
    --strict — while the output files are still written
  * a **JSON sidecar** report, which keeps the CSV schema untouched: no extra
    columns, no trailer rows, nothing that would break a CSV parser

The verdict used to live in the last transaction's ``notes`` cell, which made a
file-level result look like a property of one arbitrary row. That is asserted
gone.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

CLEAN = FIXTURES / "passbook_clean.pdf"          # balances reconcile
MISMATCH = FIXTURES / "passbook_mismatch.pdf"    # employer side off by 400
NO_BALANCES = FIXTURES / "passbook_9col.pdf"     # prints no opening/closing

EXIT_OK = 0
EXIT_BALANCE_MISMATCH = 3
EXIT_BALANCE_UNCHECKED = 4

# The documented CSV columns. A caller parses these; the integrity signal must
# never add to them.
EXPECTED_COLUMNS = [
    "date",
    "particulars",
    "transaction_type",
    "direction",
    "employee_contribution",
    "employer_contribution",
    "total_contribution",
    "notes",
]


def run_cli(pdf: Path, *extra: str):
    """Run the CLI as a subprocess, the way a caller would."""
    tmp = tempfile.mkdtemp()
    proc = subprocess.run(
        [sys.executable, "-m", "epf_reader.cli",
         "--input", str(pdf), "--output-dir", tmp, *extra],
        capture_output=True, text=True, timeout=180,
    )
    return proc, Path(tmp)


class TestExitCodes(unittest.TestCase):
    def test_reconciling_passbook_exits_zero(self):
        proc, _ = run_cli(CLEAN)
        self.assertEqual(proc.returncode, EXIT_OK, proc.stdout[-2000:])

    def test_mismatch_exits_with_its_own_code(self):
        proc, _ = run_cli(MISMATCH)
        self.assertEqual(proc.returncode, EXIT_BALANCE_MISMATCH, proc.stdout[-2000:])

    def test_mismatch_still_writes_every_output_file(self):
        """A non-zero code must mean "finished but suspect", never "no output"."""
        proc, out = run_cli(MISMATCH)
        self.assertEqual(proc.returncode, EXIT_BALANCE_MISMATCH)
        for name in ("epf_transactions.csv", "epf_transactions_metadata.csv",
                     "epf_transactions_summary.txt", "epf_transactions_report.json"):
            with self.subTest(file=name):
                self.assertTrue((out / name).is_file(), f"{name} missing")

    def test_unchecked_balances_pass_by_default(self):
        proc, _ = run_cli(NO_BALANCES)
        self.assertEqual(proc.returncode, EXIT_OK)

    def test_unchecked_balances_fail_under_strict(self):
        proc, _ = run_cli(NO_BALANCES, "--strict")
        self.assertEqual(proc.returncode, EXIT_BALANCE_UNCHECKED)

    def test_strict_does_not_change_a_reconciling_run(self):
        proc, _ = run_cli(CLEAN, "--strict")
        self.assertEqual(proc.returncode, EXIT_OK)


class TestJSONReport(unittest.TestCase):
    def test_report_is_valid_json_with_a_schema_marker(self):
        _, out = run_cli(CLEAN)
        data = json.loads((out / "epf_transactions_report.json").read_text())
        self.assertEqual(data["schema"], "epf-reader/report/1")

    def test_report_states_the_verdict_structurally(self):
        _, out = run_cli(MISMATCH)
        data = json.loads((out / "epf_transactions_report.json").read_text())
        check = data["balance_check"]
        self.assertTrue(check["checked"])
        self.assertFalse(check["ok"])
        self.assertFalse(data["ok"])
        self.assertAlmostEqual(check["employer"]["difference"], 400.0, places=2)
        self.assertAlmostEqual(check["employee"]["difference"], 0.0, places=2)

    def test_report_says_ok_when_it_reconciles(self):
        _, out = run_cli(CLEAN)
        data = json.loads((out / "epf_transactions_report.json").read_text())
        self.assertTrue(data["ok"])
        self.assertTrue(data["balance_check"]["ok"])
        self.assertEqual(data["balance_check"]["messages"], [])

    def test_report_distinguishes_unchecked_from_ok(self):
        _, out = run_cli(NO_BALANCES)
        data = json.loads((out / "epf_transactions_report.json").read_text())
        self.assertFalse(data["balance_check"]["checked"])

    def test_report_carries_counts_and_method(self):
        _, out = run_cli(CLEAN)
        data = json.loads((out / "epf_transactions_report.json").read_text())
        self.assertEqual(data["transactions"]["count"], 12)
        self.assertEqual(data["extraction"]["method"], "pdfplumber")
        self.assertEqual(data["transactions"]["by_type"]["INTEREST"], 1)

    def test_report_path_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "my-report.json"
            proc, _ = run_cli(CLEAN, "--report", str(target))
            self.assertEqual(proc.returncode, EXIT_OK)
            self.assertTrue(target.is_file())
            json.loads(target.read_text())


class TestCSVIsUndisturbed(unittest.TestCase):
    """The integrity signal must not break anyone parsing the CSV."""

    def _rows(self, pdf):
        _, out = run_cli(pdf)
        with (out / "epf_transactions.csv").open() as fh:
            return list(csv.DictReader(fh))

    def test_columns_are_unchanged_on_a_mismatch(self):
        for pdf in (CLEAN, MISMATCH):
            with self.subTest(pdf=pdf.name):
                rows = self._rows(pdf)
                self.assertEqual(list(rows[0].keys()), EXPECTED_COLUMNS)

    def test_every_row_has_the_full_column_count(self):
        """No trailer line, no ragged row — csv.reader sees a clean rectangle."""
        _, out = run_cli(MISMATCH)
        with (out / "epf_transactions.csv").open() as fh:
            widths = {len(r) for r in csv.reader(fh)}
        self.assertEqual(widths, {len(EXPECTED_COLUMNS)})

    def test_amounts_still_parse_as_numbers(self):
        for row in self._rows(MISMATCH):
            float(row["employee_contribution"])
            float(row["employer_contribution"])

    def test_notes_no_longer_carries_the_file_level_verdict(self):
        for pdf in (CLEAN, MISMATCH):
            with self.subTest(pdf=pdf.name):
                notes = " ".join(r["notes"] for r in self._rows(pdf))
                self.assertNotIn("Balance verification", notes)
                self.assertNotIn("MISMATCH", notes)


class TestLibraryAPI(unittest.TestCase):
    def test_balance_check_is_serialisable(self):
        from epf_reader import check_balances

        check = check_balances(
            [{"employee_contribution": 100.0, "employer_contribution": 50.0}],
            {"employee": 10.0, "employer": 5.0},
            {"employee": 110.0, "employer": 55.0},
        )
        payload = json.loads(json.dumps(check.to_dict()))
        self.assertTrue(payload["checked"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["employee"]["calculated"], 110.0)

    def test_verify_transactions_no_longer_writes_notes(self):
        from epf_reader.transaction_parser import verify_transactions

        txns = [{"employee_contribution": 1.0, "employer_contribution": 1.0, "notes": ""}]
        out = verify_transactions(txns, {"employee": 100.0}, {"employee": 0.0})
        self.assertEqual(out[0]["notes"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
