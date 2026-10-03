#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""Importable EPF passbook reader.

The CLI in ``main.py`` prints a report and calls ``sys.exit()`` on failure, which
makes it awkward to drive from a long-running process such as a Streamlit app.
This module runs the same pipeline as a library: no printing, no ``sys.exit``,
everything handed back as data.

    from epf_reader import read_epf_passbook

    result = read_epf_passbook("passbook.pdf")
    result.transactions   # pandas DataFrame
    result.header         # dict (PII already redacted unless you opt out)
    result.opening_balance / result.closing_balance
    result.warnings       # list[str] - soft problems, output still usable
    result.errors         # list[str] - validation failures
    result.balance_check  # opening + transactions == closing? (see BalanceCheck)

Install the package and import it from anywhere::

    pip install epf-reader
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .csv_exporter import redact_header_info, redact_transactions
from .pdf_analyzer import analyze_pdf
from .table_extractor import (
    clean_extracted_tables,
    extract_tables,
    merge_multi_page_tables,
)
from .transaction_parser import parse_transactions, verify_transactions
from .validator import validate_transactions

METHODS = ("auto", "pdfplumber", "tabula", "camelot", "ocr")


class EPFReadError(RuntimeError):
    """Raised when the passbook could not be read at all."""


@dataclass
class BalanceCheck:
    """Does opening + every transaction equal the closing balance?

    A passbook prints its own opening and closing balances, so the extraction
    can be checked against the statement itself: if the rows in between do not
    account for the difference, rows were dropped, duplicated or misparsed and
    nothing in the table should be trusted.

    ``checked`` is False when the passbook printed no balances to check against
    — that is "unknown", not "fine".
    """

    checked: bool = False
    ok: bool = True
    employee_calculated: float = 0.0
    employee_expected: float = 0.0
    employer_calculated: float = 0.0
    employer_expected: float = 0.0

    TOLERANCE = 0.01

    @property
    def employee_diff(self) -> float:
        return abs(self.employee_calculated - self.employee_expected)

    @property
    def employer_diff(self) -> float:
        return abs(self.employer_calculated - self.employer_expected)

    def to_dict(self) -> dict:
        """JSON-serialisable form, for machine-readable reports."""
        return {
            "checked": self.checked,
            "ok": self.ok,
            "employee": {
                "calculated": self.employee_calculated,
                "expected": self.employee_expected,
                "difference": round(self.employee_diff, 2),
            },
            "employer": {
                "calculated": self.employer_calculated,
                "expected": self.employer_expected,
                "difference": round(self.employer_diff, 2),
            },
            "tolerance": self.TOLERANCE,
            "messages": self.describe(),
        }

    def describe(self) -> list[str]:
        """One line per side that does not reconcile."""
        lines = []
        if self.employee_diff > self.TOLERANCE:
            lines.append(
                f"Employee: transactions give ₹{self.employee_calculated:,.2f}, "
                f"passbook says ₹{self.employee_expected:,.2f} "
                f"(off by ₹{self.employee_diff:,.2f})"
            )
        if self.employer_diff > self.TOLERANCE:
            lines.append(
                f"Employer: transactions give ₹{self.employer_calculated:,.2f}, "
                f"passbook says ₹{self.employer_expected:,.2f} "
                f"(off by ₹{self.employer_diff:,.2f})"
            )
        return lines


def check_balances(
    transactions: list[dict], opening: dict, closing: dict
) -> BalanceCheck:
    """Reconcile opening + transactions against the printed closing balance."""
    open_emp = float(opening.get("employee", 0) or 0)
    open_empr = float(opening.get("employer", 0) or 0)
    close_emp = float(closing.get("employee", 0) or 0)
    close_empr = float(closing.get("employer", 0) or 0)

    # Nothing to check against if the passbook printed no balances.
    if not any((open_emp, open_empr, close_emp, close_empr)):
        return BalanceCheck(checked=False)

    calc_emp = open_emp + sum(
        float(t.get("employee_contribution", 0) or 0) for t in transactions
    )
    calc_empr = open_empr + sum(
        float(t.get("employer_contribution", 0) or 0) for t in transactions
    )

    check = BalanceCheck(
        checked=True,
        employee_calculated=round(calc_emp, 2),
        employee_expected=round(close_emp, 2),
        employer_calculated=round(calc_empr, 2),
        employer_expected=round(close_empr, 2),
    )
    check.ok = not check.describe()
    return check


@dataclass
class EPFResult:
    """Everything one passbook yielded."""

    transactions: pd.DataFrame
    header: dict[str, Any]
    opening_balance: dict[str, Any] = field(default_factory=dict)
    closing_balance: dict[str, Any] = field(default_factory=dict)
    method_used: str = "auto"
    pages: int = 0
    is_text_based: bool = True
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    balance_check: BalanceCheck = field(default_factory=BalanceCheck)

    @property
    def type_counts(self) -> dict[str, int]:
        """Transaction count per transaction_type."""
        if self.transactions.empty or "transaction_type" not in self.transactions:
            return {}
        return self.transactions["transaction_type"].value_counts().to_dict()

    def totals(self) -> dict[str, float]:
        """Summed contribution columns, for a quick sanity display."""
        cols = (
            "employee_contribution",
            "employer_contribution",
            "pension_contribution",
        )
        return {
            c: float(pd.to_numeric(self.transactions[c], errors="coerce").fillna(0).sum())
            for c in cols
            if c in self.transactions
        }


def read_epf_passbook(
    pdf_path: str | Path,
    method: str = "auto",
    redact_pii: bool = True,
    validate: bool = True,
) -> EPFResult:
    """Read an EPF passbook PDF and return its transactions.

    Args:
        pdf_path: Path to the passbook PDF.
        method: One of ``auto``, ``pdfplumber``, ``tabula``, ``camelot``,
            ``ocr``. ``auto`` lets the analyzer pick — ``pdfplumber`` for a PDF
            with a text layer, ``ocr`` for a scanned one. A missing or failing
            tabula/camelot falls back to pdfplumber on a text PDF, never to OCR.
        redact_pii: Mask UAN, PF account, member name, establishment, DOB,
            address, email and phone before returning. On by default, matching
            the CLI.
        validate: Run the validator and populate ``errors`` / ``warnings``.

    Raises:
        EPFReadError: no tables found, or no transactions parsed.
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, got {method!r}")

    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise EPFReadError(f"PDF not found: {pdf_path}")

    analysis = analyze_pdf(str(pdf_path))
    resolved_method = analysis.get("method", "pdfplumber") if method == "auto" else method

    raw_tables = extract_tables(str(pdf_path), analysis, method=method)
    if not raw_tables:
        raise EPFReadError(
            "No tables extracted from the PDF. If this is a scanned passbook, "
            "try method='ocr' and check that Tesseract is installed."
        )

    cleaned_tables, balance_metadata = clean_extracted_tables(raw_tables)
    if not cleaned_tables:
        raise EPFReadError("Tables were extracted but held no recognisable passbook rows.")

    merged = merge_multi_page_tables(cleaned_tables)
    transactions = parse_transactions(merged)

    # Interest rows live in the balance metadata, not the transaction table.
    for interest_row in balance_metadata.get("interest_rows", []):
        transactions.append(
            {
                "date": interest_row["date"],
                "particulars": interest_row["particulars"],
                "transaction_type": "INTEREST",
                "employee_contribution": interest_row["employee"],
                "employer_contribution": interest_row["employer"],
                "notes": "Interest credited",
            }
        )

    if not transactions:
        raise EPFReadError("No transactions could be parsed from the extracted tables.")

    transactions.sort(key=lambda t: datetime.strptime(t["date"], "%d/%m/%Y"))

    opening = balance_metadata.get("opening_balance", {}) or {}
    closing = balance_metadata.get("closing_balance", {}) or {}
    transactions = verify_transactions(transactions, opening, closing)

    # verify_transactions records a mismatch only as text in the last row's
    # 'notes' cell, which is too easy to miss. Compute it as structured data so
    # callers can refuse to trust the table.
    balance_check = check_balances(transactions, opening, closing)

    is_valid, errors, warnings = True, [], []
    if validate:
        is_valid, errors, warnings = validate_transactions(transactions, analysis["header"])

    header = analysis.get("header", {}) or {}
    if redact_pii:
        transactions = redact_transactions(transactions, True)
        header = redact_header_info(header, True)

    return EPFResult(
        transactions=pd.DataFrame(transactions),
        header=header,
        opening_balance=opening,
        closing_balance=closing,
        method_used=resolved_method,
        pages=analysis.get("pages", 0),
        is_text_based=bool(analysis.get("is_text_based", True)),
        is_valid=is_valid,
        errors=list(errors),
        warnings=list(warnings),
        balance_check=balance_check,
    )


