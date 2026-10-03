# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""Read an EPFO member passbook PDF into structured transactions.

    from epf_reader import read_epf_passbook

    res = read_epf_passbook("passbook.pdf")   # PII redacted by default
    res.transactions                          # pandas DataFrame
    res.balance_check                         # does it reconcile?

Everything runs locally; the package makes no network calls.
"""

from .reader import METHODS, BalanceCheck, EPFReadError, EPFResult, read_epf_passbook

__all__ = [
    "read_epf_passbook",
    "EPFResult",
    "BalanceCheck",
    "EPFReadError",
    "METHODS",
    "__version__",
]

__version__ = "1.0.0"
