# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""EPF passbook reader — Streamlit page.

Run it directly::

    epf-ui
    # or: streamlit run $(python -c "import epf_reader.streamlit_page as m; print(m.__file__)")

Or symlink this file into an existing Streamlit app's ``pages/`` directory;
install the package into that app's environment first.

OCR is slow, so results are cached on the uploaded bytes — changing the method
or the redaction toggle re-reads, clicking around does not.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from epf_reader.doctor import collect as _collect_health
from epf_reader.reader import EPFReadError, read_epf_passbook

st.set_page_config(page_title="EPF Passbook Reader", page_icon="🏦", layout="wide")
st.title("EPF Passbook Reader")


# --------------------------------------------------------------------------
# Preflight — surface missing native deps before the user uploads anything
# --------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def _preflight() -> dict:
    return _collect_health()


try:
    health = _preflight()
except Exception:
    health = {"ready": True, "missing_core": [], "ocr_ready": True}

if not health.get("ready", True):
    # Missing Python packages — nothing can be read at all.
    missing = ", ".join(health.get("missing_core", []))
    st.error(
        f"Missing Python packages: **{missing}**. Nothing can be read until these are "
        "installed — run `epf-doctor` for per-item commands."
    )
elif not health.get("ocr_ready", True):
    # A text/table PDF needs none of this, so it is a caption, not an alarm.
    missing = ", ".join(health.get("missing_ocr", []))
    st.caption(
        f"Text PDFs are fully supported. Scanned passbooks would additionally need "
        f"**{missing}** — install only if your PDF has no selectable text."
    )

st.markdown(
    "Upload an EPF passbook PDF (download it from the EPFO member portal) to pull out "
    "its contribution and interest rows."
)


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------
uploaded = st.file_uploader("EPF passbook PDF", type=["pdf"])

with st.expander("Extraction settings", expanded=False):
    method = st.selectbox(
        "Extraction method",
        options=["auto", "pdfplumber", "ocr", "tabula", "camelot"],
        index=0,
        help=(
            "`auto` inspects the PDF and picks: `pdfplumber` when there is a text "
            "layer, `ocr` when the pages are scanned images. `pdfplumber` needs "
            "nothing beyond pip; `ocr` needs Tesseract and is much slower; "
            "`tabula` needs Java and `camelot` needs Ghostscript."
        ),
    )
    redact_pii = st.checkbox(
        "Redact personal details (UAN, PF account, name, establishment)",
        value=True,
        help="Masks identifiers in the table, metadata and downloads. On by default.",
    )
    run_validation = st.checkbox("Run validation checks", value=True)


@st.cache_data(show_spinner=False, max_entries=8)
def _read(pdf_bytes: bytes, method: str, redact_pii: bool, validate: bool) -> dict:
    """Cached on the uploaded bytes + settings, so reruns don't re-OCR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "passbook.pdf"
        pdf_path.write_bytes(pdf_bytes)
        res = read_epf_passbook(
            pdf_path, method=method, redact_pii=redact_pii, validate=validate
        )
    return {
        "transactions": res.transactions,
        "header": res.header,
        "opening_balance": res.opening_balance,
        "closing_balance": res.closing_balance,
        "method_used": res.method_used,
        "pages": res.pages,
        "is_text_based": res.is_text_based,
        "is_valid": res.is_valid,
        "errors": res.errors,
        "warnings": res.warnings,
        "type_counts": res.type_counts,
        "balance_ok": res.balance_check.ok,
        "balance_checked": res.balance_check.checked,
        "balance_detail": res.balance_check.describe(),
    }


if uploaded is None:
    st.info("Waiting for a PDF. Scanned passbooks are handled too — OCR takes a minute or two.")
    st.stop()

try:
    with st.spinner("Reading passbook… OCR on a scanned PDF can take a minute."):
        result = _read(uploaded.getvalue(), method, redact_pii, run_validation)
except EPFReadError as exc:
    st.error(f"Could not read this passbook: {exc}")
    st.stop()
except Exception as exc:
    st.error(f"Extraction failed: `{type(exc).__name__}: {exc}`")
    with st.expander("Traceback"):
        import traceback

        st.code(traceback.format_exc())
    st.stop()

df: pd.DataFrame = result["transactions"]


# --------------------------------------------------------------------------
# Integrity first — nothing below is trustworthy if the balances don't add up
# --------------------------------------------------------------------------
if result["balance_checked"] and not result["balance_ok"]:
    st.error(
        "**Balance mismatch — do not import this.** The passbook's own opening and "
        "closing balances do not match the transactions extracted between them, "
        "which means rows were dropped, duplicated or misread. Nothing in the "
        "table below can be trusted until this reconciles."
    )
    for line in result["balance_detail"]:
        st.markdown(f"- {line}")
    st.caption(
        "Try a different extraction method above. If the gap persists, the layout "
        "is one the parser does not handle — run `epf-inspect` on the file."
    )
elif not result["balance_checked"]:
    st.warning(
        "This passbook printed no opening/closing balances, so the extraction "
        "could not be checked against the statement itself. Verify the totals "
        "by hand before importing."
    )

if result["errors"]:
    st.error(f"Validation found {len(result['errors'])} error(s) — check before importing.")
    with st.expander("Errors", expanded=True):
        for err in result["errors"]:
            st.markdown(f"- {err}")

if result["warnings"]:
    with st.expander(f"⚠️ {len(result['warnings'])} warning(s)"):
        for warn in result["warnings"]:
            st.markdown(f"- {warn}")

if not result["errors"] and not result["warnings"] and result.get("balance_ok"):
    if result["balance_checked"]:
        st.success(
            f"Read {len(df)} transactions — validation clean and balances reconcile."
        )
    else:
        st.caption(f"Read {len(df)} transactions — validation clean.")
else:
    st.caption(f"Read {len(df)} transactions.")


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Transactions", len(df))
c2.metric("Pages", result["pages"])
c3.metric("Method", result["method_used"])
c4.metric("PDF type", "Text" if result["is_text_based"] else "Scanned")

opening, closing = result["opening_balance"], result["closing_balance"]
if opening or closing:
    b1, b2 = st.columns(2)
    with b1:
        st.markdown(f"**Opening balance** · as on {opening.get('date', 'N/A')}")
        st.markdown(
            f"- Employee: ₹{opening.get('employee', 0):,.2f}\n"
            f"- Employer: ₹{opening.get('employer', 0):,.2f}\n"
            f"- **Total: ₹{opening.get('employee', 0) + opening.get('employer', 0):,.2f}**"
        )
    with b2:
        st.markdown(f"**Closing balance** · as on {closing.get('date', 'N/A')}")
        st.markdown(
            f"- Employee: ₹{closing.get('employee', 0):,.2f}\n"
            f"- Employer: ₹{closing.get('employer', 0):,.2f}\n"
            f"- **Total: ₹{closing.get('employee', 0) + closing.get('employer', 0):,.2f}**"
        )

if result["type_counts"]:
    st.caption(
        "Transaction types — "
        + " · ".join(f"{k}: {v}" for k, v in sorted(result["type_counts"].items()))
    )

if result["header"]:
    with st.expander("Passbook metadata"):
        meta = {k: v for k, v in result["header"].items() if v}
        if redact_pii:
            st.caption("Personal identifiers are redacted. Untick the setting above to see raw values.")
        st.dataframe(
            pd.DataFrame(sorted(meta.items()), columns=["Field", "Value"]),
            hide_index=True,
        )


# --------------------------------------------------------------------------
# Transactions + downloads
# --------------------------------------------------------------------------
display = df.copy()
if "date" in display:
    display["date"] = pd.to_datetime(display["date"], format="%d/%m/%Y", errors="coerce")

st.dataframe(
    display,
    hide_index=True,
    column_config={"date": st.column_config.DateColumn("Date", format="DD/MM/YYYY")}
    if "date" in display
    else None,
)

stem = Path(uploaded.name).stem
d1, d2 = st.columns(2)

d1.download_button(
    "Download transactions CSV",
    data=df.to_csv(index=False).encode("utf-8"),
    file_name=f"{stem}_epf_transactions.csv",
    mime="text/csv",
)

if result["header"]:
    meta_csv = pd.DataFrame(
        sorted((k, v) for k, v in result["header"].items() if v), columns=["Field", "Value"]
    )
    d2.download_button(
        "Download metadata CSV",
        data=meta_csv.to_csv(index=False).encode("utf-8"),
        file_name=f"{stem}_epf_metadata.csv",
        mime="text/csv",
    )
