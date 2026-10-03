# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""
Table Extractor Module
Extract tables from EPF passbook PDFs using multiple methods (Tabula, Camelot, OCR)
"""

import pandas as pd
from typing import List, Dict, Optional, Tuple
import re

# Optional alternative backends. Their absence is normal and handled — the
# extraction falls back on its own — so importing this module stays silent
# rather than printing a warning on every import. `epf-doctor` reports what is
# installed when someone actually wants to know.
try:
    import tabula
    TABULA_AVAILABLE = True
except ImportError:
    TABULA_AVAILABLE = False

try:
    import camelot
    CAMELOT_AVAILABLE = True
except ImportError:
    CAMELOT_AVAILABLE = False

# pdfplumber is a core dependency, not an optional backend: pure Python, no
# Java, Ghostscript or Tesseract, and it reads a text/table PDF directly.
import pdfplumber



def extract_tables(pdf_path: str, analysis: Dict, method: str = 'auto') -> List[pd.DataFrame]:
    """
    Extract tables from PDF using specified method
    
    Args:
        pdf_path: Path to PDF file
        analysis: Analysis dict from pdf_analyzer
        method: 'auto', 'tabula', 'camelot', or 'ocr'
        
    Returns:
        List of pandas DataFrames (one per page/table)
    """
    # Auto-select method if not specified
    if method == 'auto':
        method = analysis.get('method', 'pdfplumber')
    
    print(f"Extracting tables using method: {method}")
    
    if method == 'pdfplumber':
        return extract_with_pdfplumber(pdf_path, analysis)
    elif method == 'tabula':
        return extract_with_tabula(pdf_path, analysis)
    elif method == 'camelot':
        return extract_with_camelot(pdf_path, analysis)
    elif method == 'ocr':
        return extract_with_ocr(pdf_path, analysis)
    else:
        raise ValueError(f"Unknown extraction method: {method}")


def _text_fallback(pdf_path: str, analysis: Dict) -> List[pd.DataFrame]:
    """Where to go when an optional backend is missing or fails.

    A text-based PDF must never land in OCR just because Java or Ghostscript is
    absent — pdfplumber reads it directly, faster and without transcription
    error. Only a genuinely scanned page needs the OCR path.
    """
    if analysis.get('is_text_based', True):
        print("Falling back to pdfplumber (text-based PDF, no OCR needed)...")
        return extract_with_pdfplumber(pdf_path, analysis)
    print("Falling back to OCR (scanned PDF)...")
    return extract_with_ocr(pdf_path, analysis)


def extract_with_pdfplumber(pdf_path: str, analysis: Dict) -> List[pd.DataFrame]:
    """Extract tables with pdfplumber — the default path for text/table PDFs.

    Tries the ruled-line strategy first (an EPF passbook is normally drawn as a
    bordered grid), then whitespace alignment for borderless layouts, keeping
    whichever recovers more rows on each page. Returns one DataFrame per page
    with every row as data and no header consumed, which is the shape
    ``clean_extracted_tables`` expects.

    Args:
        pdf_path: Path to PDF file
        analysis: Analysis dict

    Returns:
        List of DataFrames
    """
    strategies = [
        {'vertical_strategy': 'lines', 'horizontal_strategy': 'lines'},
        {
            'vertical_strategy': 'text',
            'horizontal_strategy': 'text',
            'intersection_tolerance': 5,
            'text_tolerance': 2,
        },
    ]

    all_tables: List[pd.DataFrame] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"pdfplumber reading {len(pdf.pages)} page(s)...")

            for page_num, page in enumerate(pdf.pages, 1):
                best: Optional[pd.DataFrame] = None

                for settings in strategies:
                    try:
                        tables = page.extract_tables(table_settings=settings)
                    except Exception as exc:
                        print(f"  page {page_num}: strategy failed ({exc})")
                        continue

                    for table in tables or []:
                        df = _rows_to_dataframe(table)
                        if df is None:
                            continue
                        if best is None or len(df) > len(best):
                            best = df

                    # A ruled grid that produced real rows is trustworthy; don't
                    # let the looser text strategy override it.
                    if best is not None and len(best) > 1:
                        break

                if best is not None:
                    print(f"  page {page_num}: {len(best)} row(s) x {len(best.columns)} col(s)")
                    all_tables.append(best)
                else:
                    print(f"  page {page_num}: no table found")

    except Exception as exc:
        print(f"pdfplumber extraction failed: {exc}")
        return []

    print(f"pdfplumber extracted {len(all_tables)} table(s)")
    return all_tables


def _rows_to_dataframe(rows) -> Optional[pd.DataFrame]:
    """Turn pdfplumber's list-of-rows into a header-less DataFrame.

    pdfplumber yields None for an empty cell and keeps the newlines a wrapped
    cell carries; both confuse the downstream string matching, so they are
    normalised here. Short rows are padded so the frame stays rectangular —
    a merged cell can otherwise shorten one.
    """
    if not rows:
        return None

    cleaned = []
    for row in rows:
        if row is None:
            continue
        cells = [' '.join((cell or '').split()) for cell in row]
        if any(cells):
            cleaned.append(cells)

    if not cleaned:
        return None

    width = max(len(r) for r in cleaned)
    cleaned = [r + [''] * (width - len(r)) for r in cleaned]

    return pd.DataFrame(cleaned)


def extract_with_tabula(pdf_path: str, analysis: Dict) -> List[pd.DataFrame]:
    """
    Extract tables using Tabula-py (best for text-based PDFs)
    
    Args:
        pdf_path: Path to PDF file
        analysis: Analysis dict
        
    Returns:
        List of DataFrames
    """
    if not TABULA_AVAILABLE:
        print("Tabula not available.")
        return _text_fallback(pdf_path, analysis)
    
    try:
        # Get table region
        region = analysis.get('table_region', {})
        
        # Extract tables from all pages
        dfs = tabula.read_pdf(
            pdf_path,
            pages='all',
            lattice=False,  # Stream mode for non-bordered tables
            stream=True,
            guess=True,
            multiple_tables=False,
            pandas_options={'header': None}
        )
        
        if not dfs:
            print("Tabula found no tables, trying with lattice mode...")
            dfs = tabula.read_pdf(
                pdf_path,
                pages='all',
                lattice=True,  # Lattice mode for bordered tables
                pandas_options={'header': None}
            )
        
        print(f"Tabula extracted {len(dfs)} table(s)")
        return dfs if dfs else []
        
    except Exception as e:
        print(f"Tabula extraction failed: {e}")
        print("Falling back to Camelot...")
        return extract_with_camelot(pdf_path, analysis)


def extract_with_camelot(pdf_path: str, analysis: Dict) -> List[pd.DataFrame]:
    """
    Extract tables using Camelot-py (best for bordered tables)
    
    Args:
        pdf_path: Path to PDF file
        analysis: Analysis dict
        
    Returns:
        List of DataFrames
    """
    if not CAMELOT_AVAILABLE:
        print("Camelot not available.")
        return _text_fallback(pdf_path, analysis)
    
    try:
        # Try lattice mode first (for bordered tables)
        tables = camelot.read_pdf(
            pdf_path,
            pages='1-end',
            flavor='lattice'
        )
        
        if len(tables) == 0:
            print("Camelot lattice found no tables, trying stream mode...")
            tables = camelot.read_pdf(
                pdf_path,
                pages='1-end',
                flavor='stream'
            )
        
        # Convert to list of DataFrames
        dfs = [table.df for table in tables]
        
        print(f"Camelot extracted {len(dfs)} table(s)")
        return dfs
        
    except Exception as e:
        print(f"Camelot extraction failed: {e}")
        return _text_fallback(pdf_path, analysis)


def extract_with_ocr(pdf_path: str, analysis: Dict) -> List[pd.DataFrame]:
    """
    Extract tables using Tesseract OCR (for scanned PDFs)
    
    Args:
        pdf_path: Path to PDF file
        analysis: Analysis dict
        
    Returns:
        List of DataFrames
    """
    print("Using OCR extraction (this may take longer)...")

    # Imported here, not at module scope: Tesseract/Poppler/OpenCV are an
    # optional extra (pip install "epf-reader[ocr]"), and a text PDF never
    # reaches this function. A module-level import would make them mandatory.
    try:
        import pytesseract
        from pdf2image import convert_from_path

        from .image_preprocessor import preprocess_image
    except ImportError as exc:
        print(f"OCR dependencies are not installed ({exc}).")
        print('Install them with:  pip install "epf-reader[ocr]"')
        return []

    try:
        # Convert PDF to images
        dpi = analysis.get('dpi', 300)
        images = convert_from_path(pdf_path, dpi=dpi)
        
        print(f"Processing {len(images)} page(s) with OCR...")
        
        all_tables = []
        
        for page_num, image in enumerate(images, 1):
            print(f"  Processing page {page_num}/{len(images)}...")
            
            # Preprocess image
            processed_image = preprocess_image(image)
            
            # Perform OCR
            text = pytesseract.image_to_string(
                processed_image,
                config='--psm 6'  # Assume uniform block of text
            )
            
            # Parse OCR text into table
            df = parse_ocr_text_to_table(text)
            
            if df is not None and len(df) > 0:
                all_tables.append(df)
        
        print(f"OCR extracted {len(all_tables)} table(s)")
        return all_tables
        
    except Exception as e:
        print(f"OCR extraction failed: {e}")
        return []


def parse_ocr_text_to_table(text: str) -> Optional[pd.DataFrame]:
    """
    Parse OCR text into structured table format
    
    Args:
        text: Raw OCR text
        
    Returns:
        DataFrame or None if parsing fails
    """
    if not text or len(text.strip()) < 50:
        return None
    
    # Split into lines
    lines = text.split('\n')
    
    # Filter out empty lines
    lines = [line.strip() for line in lines if line.strip()]
    
    # Find lines that look like transaction rows (have dates or amounts)
    transaction_lines = []
    
    for line in lines:
        # Skip header lines
        if any(keyword in line.upper() for keyword in [
            'DATE', 'PERIOD', 'PARTICULARS', 'EMPLOYEE', 'EMPLOYER', 'PENSION', 'TOTAL', 'BALANCE'
        ]):
            continue
        
        # Look for lines with dates or amounts
        has_date = bool(re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', line))
        has_month = bool(re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)', line, re.IGNORECASE))
        has_amount = bool(re.search(r'\d{1,3}(,\d{2,3})*\.\d{2}', line))
        
        if (has_date or has_month) and has_amount:
            transaction_lines.append(line)
    
    if not transaction_lines:
        return None
    
    # Parse each line into columns
    rows = []
    for line in transaction_lines:
        row = parse_transaction_line(line)
        if row:
            rows.append(row)
    
    if not rows:
        return None
    
    # Create DataFrame
    df = pd.DataFrame(rows)
    
    return df


def parse_transaction_line(line: str) -> Optional[Dict]:
    """
    Parse a single transaction line from OCR text
    
    Args:
        line: Single line of text
        
    Returns:
        Dictionary with parsed fields or None
    """
    # This is a simplified parser - real implementation would be more robust
    
    # Extract date/period (first field)
    date_match = re.search(r'^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Z]{3,9}\s+\d{4})', line, re.IGNORECASE)
    if not date_match:
        return None
    
    date = date_match.group(1)
    remaining = line[len(date):].strip()
    
    # Extract all amounts (Indian format with commas)
    amounts = re.findall(r'[-]?\d{1,3}(,\d{2,3})*\.\d{2}', remaining)
    
    # Extract particulars (text between date and first amount)
    if amounts:
        first_amount_pos = remaining.find(amounts[0])
        particulars = remaining[:first_amount_pos].strip()
    else:
        particulars = remaining
        amounts = []
    
    # Parse amounts (expecting: employee, employer, pension, total)
    employee = float(amounts[0].replace(',', '')) if len(amounts) > 0 else 0.0
    employer = float(amounts[1].replace(',', '')) if len(amounts) > 1 else 0.0
    pension = float(amounts[2].replace(',', '')) if len(amounts) > 2 else 0.0
    total = float(amounts[3].replace(',', '')) if len(amounts) > 3 else 0.0
    
    return {
        'col0': date,
        'col1': particulars,
        'col2': employee,
        'col3': employer,
        'col4': pension,
        'col5': total
    }


def parse_indian_amount(amount) -> float:
    """Parse Indian amount format with commas"""
    if pd.isna(amount) or not amount or amount == '':
        return 0.0
    amount_str = str(amount).replace(',', '').replace('₹', '').replace('Rs.', '').replace('Rs', '').strip()
    try:
        return float(amount_str)
    except:
        return 0.0


# An amount must carry a decimal part or a thousands comma. Requiring one of
# the two is what keeps a date cell ("01/04/2023") from reading as a number.
_AMOUNT_RE = re.compile(r'\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+\.\d{2}')

# Labels that mark the balance rows. Passbook layouts differ: some print
# "OB Int. Updated upto <date>", others a plain "Opening Balance".
_OPENING_LABELS = ('OB INT', 'OPENING BALANCE', 'OPENING BAL')
_CLOSING_LABELS = ('CLOSING BALANCE', 'CLOSING BAL')


# A cell that is *entirely* a number is an amount, comma-grouped or not — real
# passbooks print whole rupees ('1,250', '20,000'). Requiring a comma or decimal
# point, as the scan below must, would skip every sub-1000 figure.
_WHOLE_CELL_AMOUNT_RE = re.compile(r'^-?\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?$|^-?\d+(?:\.\d{1,2})?$')


def _row_amounts(row) -> List[float]:
    """Every amount in a row, left to right, across all cells.

    A cell holding exactly one number is taken whole; otherwise the cell is
    scanned, since a merged cell can carry several amounts on separate lines.
    Scanning requires a comma group or a decimal part so that a date
    ('01-04-2015') cannot be mistaken for a figure.
    """
    amounts = []
    for i in range(len(row)):
        cell = str(row.iloc[i]).strip()
        if _WHOLE_CELL_AMOUNT_RE.match(cell):
            amounts.append(parse_indian_amount(cell))
            continue
        for token in _AMOUNT_RE.findall(cell):
            amounts.append(parse_indian_amount(token))
    return amounts


def _extract_balance_row(df: pd.DataFrame, labels: Tuple[str, ...]) -> Dict:
    """Find a balance row by label and read its date and first two amounts.

    Scans **every** cell for the label, not just the first column: the label
    sits in the particulars column whenever the date has its own column, and
    looking only at column 0 silently returned a zero balance for those
    layouts.
    """
    for _, row in df.iterrows():
        cells = [str(row.iloc[i]) for i in range(len(row))]
        haystack = ' '.join(cells).upper()

        if not any(label in haystack for label in labels):
            continue

        date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', ' '.join(cells))
        date = date_match.group(1).replace('-', '/') if date_match else ''

        amounts = _row_amounts(row)
        if len(amounts) >= 2:
            return {'date': date, 'employee': amounts[0], 'employer': amounts[1]}

    return {'date': '', 'employee': 0, 'employer': 0}


def extract_opening_balance(df: pd.DataFrame) -> Dict:
    """Extract the opening balance row (employee, employer, date)."""
    return _extract_balance_row(df, _OPENING_LABELS)


def extract_closing_balance(df: pd.DataFrame) -> Dict:
    """Extract the closing balance row (employee, employer, date)."""
    return _extract_balance_row(df, _CLOSING_LABELS)


def extract_interest_rows(df: pd.DataFrame) -> List[Dict]:
    """Extract interest transactions from 'Int. Updated upto <date>' rows"""
    interest_transactions = []
    for idx, row in df.iterrows():
        first_col = str(row.iloc[0]).upper() if len(row) > 0 else ''
        if 'INT. UPDATED' in first_col and 'OB' not in first_col:
            match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', str(row.iloc[0]))
            date = match.group(1).replace('-', '/') if match else ''
            amounts = [str(row.iloc[i]) for i in range(len(row))]
            balance_amounts = [amt for amt in amounts if ',' in str(amt) and amt != '']
            if len(balance_amounts) >= 2:
                employee = parse_indian_amount(balance_amounts[0])
                employer = parse_indian_amount(balance_amounts[1])
                interest_transactions.append({
                    'date': date,
                    'particulars': str(row.iloc[0]).strip(),
                    'employee': employee,
                    'employer': employer
                })
    return interest_transactions



# Two different 9-column passbook layouts exist, and they cannot be told apart
# by column count:
#
#   "combined" — col0 empty, col1 holds wage month AND date in one cell
#                ['', 'Mar-2015 01-04-2015', 'CR', 'Cont. For ...', ...]
#   "split"    — col0 is the wage month, col1 the date, in their own columns
#                ['Mar-2015', '01-04-2015', 'CR', 'Cont. For ...', ...]
#
# pdfplumber's rect-based extraction yields the split form; the combined form is
# what tabula produced. Reading a split table with the combined mapping leaves
# every date NaN and silently drops all rows, so the shape is sniffed instead.
_WAGE_MONTH_RE = re.compile(r'^[A-Za-z]{3,9}[-\s]\d{4}$')
_BARE_DATE_RE = re.compile(r'^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$')
_COMBINED_RE = re.compile(r'[A-Za-z]{3,9}[-\s]\d{4}\s+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}')


def _detect_9col_variant(df: pd.DataFrame) -> str:
    """Return 'split' or 'combined' for a 9-column table.

    Decided by majority over the rows rather than the first row alone, so one
    odd row (a sub-header, a merged cell) cannot flip the whole mapping.
    """
    split_votes = 0
    combined_votes = 0

    for _, row in df.iterrows():
        col0 = str(row.iloc[0]).strip()
        col1 = str(row.iloc[1]).strip()

        if _COMBINED_RE.search(col1):
            combined_votes += 1
        elif _WAGE_MONTH_RE.match(col0) and _BARE_DATE_RE.match(col1):
            split_votes += 1
        elif not col0 and _BARE_DATE_RE.match(col1):
            # col0 empty but the date stands alone: still the split shape.
            split_votes += 1

    return 'split' if split_votes > combined_votes else 'combined'



# Column-name words that mark a header row rather than a transaction.
_HEADER_KEYWORDS = (
    'DATE', 'PERIOD', 'PARTICULARS', 'EMPLOYEE', 'EMPLOYER', 'PENSION',
    'TOTAL', 'WAGE MONTH', 'TRANSACTION', 'CONTRIBUTION', 'BALANCE',
    'FOOJ.K', 'OSRU EKG',
)

# \b around each keyword so 'DATE' matches the header cell "Transaction Date"
# but not the word "Updated" inside a transaction's particulars.
_HEADER_ROW_RE = re.compile(
    r'\b(?:' + '|'.join(re.escape(k) for k in _HEADER_KEYWORDS) + r')\b'
)


def _looks_like_header_row(row_text: str) -> bool:
    """True if a row's text reads as column headings."""
    return bool(_HEADER_ROW_RE.search(row_text.upper()))


def clean_extracted_tables(dfs: List[pd.DataFrame]) -> Tuple[List[pd.DataFrame], Dict]:
    """
    Clean and standardize extracted tables
    
    Args:
        dfs: List of raw DataFrames
        
    Returns:
        Tuple of (List of cleaned DataFrames, metadata dict with opening/closing balances)
    """
    cleaned = []
    metadata = {
        'opening_balance': {'date': '', 'employee': 0, 'employer': 0},
        'closing_balance': {'date': '', 'employee': 0, 'employer': 0},
        'interest_rows': []
    }
    
    for df in dfs:
        if df is None or len(df) == 0:
            continue
        
        # Remove completely empty rows
        df = df.dropna(how='all')
        
        # Extract opening and closing balances BEFORE filtering
        opening_balance = extract_opening_balance(df)
        closing_balance = extract_closing_balance(df)
        interest_rows = extract_interest_rows(df)
        
        # Remove header rows (rows that contain column names or Hindi text).
        # Matched on word boundaries, not as bare substrings: 'DATE' as a
        # substring also matches "Up-DATE-d", which deleted every
        # "Int. Updated upto <date>" interest row — a silent loss of the annual
        # interest credit.
        df = df[~df.astype(str).apply(
            lambda row: _looks_like_header_row(str(row)), axis=1
        )]
        
        # Remove summary/total rows (but keep them in extracted metadata)
        df = df[~df.astype(str).apply(lambda row: any(
            keyword in str(row.iloc[0] if len(row) > 0 else '').upper()
            for keyword in ['TOTAL CONTRIBUTIONS', 'TOTAL TRANSFER', 'TOTAL WITHDRAWALS', 
                           'INT. UPDATED', 'CLOSING BALANCE', 'OB INT']
        ), axis=1)]
        
        # Reset index
        df = df.reset_index(drop=True)
        
        # Standardize column names based on detected column count
        num_cols = len(df.columns)
        print(f"DEBUG: Table has {num_cols} columns")
        print(f"DEBUG: First row: {df.iloc[0].tolist() if len(df) > 0 else 'No data'}")
        
        if num_cols == 12:
            # Full format: Date, Particulars, Emp_Contrib, Empr_Contrib, Pension_Contrib, 
            # Total_Contrib, Emp_Balance, Empr_Balance, Pension_Balance, Total_Balance, Period, Notes
            df.columns = ['date', 'particulars', 'employee', 'employer', 'pension', 'total',
                         'employee_balance', 'employer_balance', 'pension_balance', 'total_balance', 
                         'period', 'notes']
        elif num_cols == 9:
            variant = _detect_9col_variant(df)
            print(f"DEBUG: 9-column layout detected as '{variant}'")

            # The CR/DR column is named 'direction' rather than
            # 'transaction_type': the parser's transaction_type holds the
            # classification (CONTRIBUTION / WITHDRAWAL / INTEREST), and
            # conflating the two is what previously let direction be dropped.
            if variant == 'split':
                # Wage Month | Date | CR/DR | Particulars | EPF Wages |
                # EPS Wages | Employee | Employer | Pension
                df.columns = ['wage_month', 'date', 'direction', 'particulars',
                              'epf_wages', 'eps_wages', 'employee', 'employer', 'pension']
            else:
                # Empty | WageMonth+Date | CR/DR | Particulars | Wages | Total |
                # Employee | Employer | Pension
                df.columns = ['empty', 'wage_month_date', 'direction', 'particulars',
                              'wages', 'total', 'employee', 'employer', 'pension']
                df = df.drop('empty', axis=1)

                split_data = df['wage_month_date'].str.extract(
                    r'([A-Za-z]+-\d{4})\s+(\d{2}-\d{2}-\d{4})', expand=True
                )
                df['wage_month'] = split_data[0]
                df['date'] = split_data[1]
                df = df.drop('wage_month_date', axis=1)

            debits = int(df['direction'].astype(str).str.strip().str.upper().eq('DR').sum())
            if debits:
                print(f"DEBUG: {debits} debit (DR) row(s) — amounts will be signed negative")

            # Keep what the parser consumes, direction included: a DR row is
            # money leaving the account, and dropping the column lost that.
            df = df[['date', 'particulars', 'employee', 'employer', 'direction']]
        elif num_cols == 6:
            # Simple format: Date, Particulars, Employee, Employer, Pension, Total (contributions only)
            df.columns = ['date', 'particulars', 'employee', 'employer', 'pension', 'total']
        elif num_cols == 5:
            # No pension column (pre-2014)
            df.columns = ['date', 'particulars', 'employee', 'employer', 'total']
            df['pension'] = 0.0
        else:
            print(f"WARNING: Unexpected column count: {num_cols}. Column names: {list(df.columns)}")
            print(f"First few rows:\n{df.head()}")
            # Try to use first row as sample to identify columns
            continue
        
        # Store metadata from first table only
        if len(cleaned) == 0 and len(df) > 0:
            metadata['opening_balance'] = opening_balance
            metadata['closing_balance'] = closing_balance
            metadata['interest_rows'] = interest_rows
        
        if len(df) > 0:
            cleaned.append(df)
    
    return cleaned, metadata


def merge_multi_page_tables(dfs: List[pd.DataFrame]) -> pd.DataFrame:
    """
    Merge tables from multiple pages into single DataFrame
    
    Args:
        dfs: List of DataFrames from different pages
        
    Returns:
        Single merged DataFrame
    """
    if not dfs:
        return pd.DataFrame()
    
    if len(dfs) == 1:
        return dfs[0]
    
    # Concatenate all DataFrames
    merged = pd.concat(dfs, ignore_index=True)
    
    # Remove duplicate rows (from repeated headers)
    merged = merged.drop_duplicates()
    
    return merged


def validate_extracted_data(df: pd.DataFrame) -> bool:
    """
    Validate extracted table data
    
    Args:
        df: DataFrame to validate
        
    Returns:
        True if valid, False otherwise
    """
    if df is None or len(df) == 0:
        print("⚠️  No data extracted")
        return False
    
    # Check for required columns
    required_cols = ['date', 'particulars', 'employee', 'employer', 'total']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        print(f"⚠️  Missing columns: {missing_cols}")
        return False
    
    # Check if we have at least some valid data
    non_null_rows = df['date'].notna().sum()
    
    if non_null_rows < 1:
        print("⚠️  No valid date entries found")
        return False
    
    print(f"✅ Extracted {len(df)} rows with {non_null_rows} valid entries")
    return True


if __name__ == "__main__":
    # Test extraction
    import sys
    from .pdf_analyzer import analyze_pdf
    
    if len(sys.argv) < 2:
        print("Usage: python table_extractor.py <pdf_path> [method]")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    method = sys.argv[2] if len(sys.argv) > 2 else 'auto'
    
    print(f"Analyzing PDF: {pdf_file}")
    analysis = analyze_pdf(pdf_file)
    
    print(f"\nExtracting tables with method: {method}")
    print("=" * 60)
    
    tables = extract_tables(pdf_file, analysis, method=method)
    
    if tables:
        print(f"\n✅ Extraction complete: {len(tables)} table(s) found")
        
        # Clean tables
        cleaned_tables = clean_extracted_tables(tables)
        
        # Merge if multiple pages
        if len(cleaned_tables) > 1:
            merged = merge_multi_page_tables(cleaned_tables)
            print(f"\n📊 Merged table: {len(merged)} rows")
            print("\nFirst 5 rows:")
            print(merged.head())
        elif len(cleaned_tables) == 1:
            print(f"\n📊 Single table: {len(cleaned_tables[0])} rows")
            print("\nFirst 5 rows:")
            print(cleaned_tables[0].head())
    else:
        print("\n❌ No tables extracted")
