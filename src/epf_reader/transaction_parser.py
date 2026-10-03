# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""
Transaction Parser Module
Parse EPF passbook transactions from raw table data into structured format
Handles Indian date/amount formats and transaction classification
"""

import re
import pandas as pd
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from decimal import Decimal


# Load configuration
CONFIG_DIR = Path(__file__).parent / 'config'

def load_config(config_file: str = 'patterns.yaml') -> Dict:
    """Load configuration from YAML file"""
    config_path = CONFIG_DIR / config_file
    if not config_path.exists():
        return {}
    
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

# Load patterns and transaction types
PATTERNS = load_config('patterns.yaml')
TRANSACTION_TYPES = load_config('transaction_types.yaml')


def parse_transactions(df: pd.DataFrame) -> List[Dict]:
    """
    Parse raw table data into structured transaction format
    
    Args:
        df: DataFrame with columns: date, particulars, employee, employer, pension, total
        
    Returns:
        List of transaction dictionaries
    """
    transactions = []
    
    for idx, row in df.iterrows():
        try:
            transaction = parse_transaction_row(row, idx)
            if transaction:
                transactions.append(transaction)
        except Exception as e:
            print(f"Warning: Error parsing row {idx}: {e}")
            continue
    
    return transactions


def parse_transaction_row(row: pd.Series, row_num: int) -> Optional[Dict]:
    """
    Parse a single transaction row
    
    Args:
        row: pandas Series with transaction data
        row_num: Row number for reference
        
    Returns:
        Transaction dictionary or None if invalid
    """
    # Extract date/period
    date_str = str(row.get('date', '')).strip()
    if not date_str or date_str == 'nan':
        return None
    
    # Parse date
    parsed_date = parse_epf_date(date_str)
    if not parsed_date:
        print(f"Warning: Could not parse date: {date_str}")
        return None
    
    # Extract particulars
    particulars = str(row.get('particulars', '')).strip()
    if not particulars or particulars == 'nan':
        particulars = ''
    
    # Classify transaction type
    transaction_type = classify_transaction(particulars)
    
    # Parse amounts (ignore pension and total)
    employee_contrib = parse_indian_amount(row.get('employee', 0))
    employer_contrib = parse_indian_amount(row.get('employer', 0))
    
    # Build transaction dictionary - only 6 columns
    transaction = {
        'date': parsed_date,
        'particulars': particulars,
        'transaction_type': transaction_type,
        'employee_contribution': employee_contrib,
        'employer_contribution': employer_contrib,
        'notes': ''
    }
    
    return transaction


def parse_epf_date(date_str: str) -> Optional[str]:
    """
    Parse EPF date in various formats to DD/MM/YYYY
    
    Supported formats:
    - DD/MM/YYYY, DD-MM-YYYY
    - April 2024, Apr 2024 (returns 01/MM/YYYY)
    - FY 2023-24 (returns 31/03/2024)
    
    Args:
        date_str: Date string
        
    Returns:
        Date in DD/MM/YYYY format or None
    """
    date_str = date_str.strip()
    
    # Try standard formats first
    date_formats = [
        '%d/%m/%Y',
        '%d-%m-%Y',
        '%d/%m/%y',
        '%d-%m-%y',
        '%d.%m.%Y',
        '%d.%m.%y'
    ]
    
    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime('%d/%m/%Y')
        except ValueError:
            continue
    
    # Try month-year format (April 2024, Apr 2024)
    month_year_match = re.match(
        r'(JAN(UARY)?|FEB(RUARY)?|MAR(CH)?|APR(IL)?|MAY|JUN(E)?|JUL(Y)?|AUG(UST)?|SEP(TEMBER)?|OCT(OBER)?|NOV(EMBER)?|DEC(EMBER)?)\s+(\d{4})',
        date_str,
        re.IGNORECASE
    )
    
    if month_year_match:
        month_str = month_year_match.group(1)
        year = month_year_match.group(14)  # Last group is the year
        
        # Map month name to number
        month_map = {
            'JAN': 1, 'JANUARY': 1,
            'FEB': 2, 'FEBRUARY': 2,
            'MAR': 3, 'MARCH': 3,
            'APR': 4, 'APRIL': 4,
            'MAY': 5,
            'JUN': 6, 'JUNE': 6,
            'JUL': 7, 'JULY': 7,
            'AUG': 8, 'AUGUST': 8,
            'SEP': 9, 'SEPTEMBER': 9,
            'OCT': 10, 'OCTOBER': 10,
            'NOV': 11, 'NOVEMBER': 11,
            'DEC': 12, 'DECEMBER': 12
        }
        
        month_num = month_map.get(month_str.upper(), 1)
        return f"01/{month_num:02d}/{year}"
    
    # Try FY format (FY 2023-24 -> 31/03/2024)
    fy_match = re.match(r'FY\s+(\d{4})-?(\d{2,4})', date_str, re.IGNORECASE)
    if fy_match:
        year = fy_match.group(2)
        # Add 2000 if only 2 digits
        if len(year) == 2:
            year = '20' + year
        return f"31/03/{year}"
    
    return None


def parse_indian_amount(amount) -> float:
    """
    Parse Indian amount format with lakhs separator
    
    Examples:
    - 1,25,000.50 -> 125000.50
    - ₹1,00,000 -> 100000.0
    - (1,000.00) -> -1000.0 (negative in parentheses)
    - -5,000.00 -> -5000.0
    
    Args:
        amount: Amount as string or number
        
    Returns:
        Float value
    """
    if pd.isna(amount):
        return 0.0
    
    if isinstance(amount, (int, float)):
        return float(amount)
    
    amount_str = str(amount).strip()
    
    if not amount_str or amount_str in ['', 'nan', 'None', '-']:
        return 0.0
    
    # Remove currency symbols
    amount_str = amount_str.replace('₹', '').replace('Rs.', '').replace('Rs', '').strip()
    
    # Handle parentheses for negative
    is_negative = False
    if amount_str.startswith('(') and amount_str.endswith(')'):
        is_negative = True
        amount_str = amount_str[1:-1]
    
    # Check for negative sign
    if amount_str.startswith('-'):
        is_negative = True
        amount_str = amount_str[1:]
    
    # Remove commas
    amount_str = amount_str.replace(',', '')
    
    # Remove spaces
    amount_str = amount_str.replace(' ', '')
    
    try:
        value = float(amount_str)
        return -value if is_negative else value
    except ValueError:
        print(f"Warning: Could not parse amount: {amount}")
        return 0.0


def extract_period(particulars: str, date_str: str) -> str:
    """
    Extract period from particulars or date
    
    Args:
        particulars: Transaction particulars text
        date_str: Date string
        
    Returns:
        Period string (e.g., "APR 2024", "FY 2023-24", "Opening", etc.)
    """
    if not particulars:
        return date_str
    
    particulars_upper = particulars.upper()
    
    # Check for opening/closing balance
    if 'OPENING' in particulars_upper:
        return 'Opening'
    if 'CLOSING' in particulars_upper:
        return 'Closing'
    
    # Extract month-year from "CONT FOR APR 2024" pattern
    month_year_match = re.search(
        r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{4})',
        particulars_upper
    )
    if month_year_match:
        month = month_year_match.group(1)
        year = month_year_match.group(2)
        return f"{month} {year}"
    
    # Extract FY from "INT FOR FY 2023-24" pattern
    fy_match = re.search(r'FY\s+(\d{4})-?(\d{2,4})', particulars_upper)
    if fy_match:
        year1 = fy_match.group(1)
        year2 = fy_match.group(2)
        if len(year2) == 2:
            year2 = year1[:2] + year2
        return f"FY {year1}-{year2}"
    
    # Fall back to date string
    return date_str


def classify_transaction(particulars: str) -> str:
    """
    Classify transaction type based on particulars text
    
    Args:
        particulars: Transaction particulars
        
    Returns:
        Transaction type: OPENING, CONTRIBUTION, INTEREST, WITHDRAWAL, TDS, etc.
    """
    if not particulars:
        return 'UNKNOWN'
    
    particulars_upper = particulars.upper()
    
    # Load transaction type config if available
    if TRANSACTION_TYPES and 'transaction_types' in TRANSACTION_TYPES:
        for txn_type, config in TRANSACTION_TYPES['transaction_types'].items():
            keywords = config.get('keywords', [])
            for keyword in keywords:
                if keyword.upper() in particulars_upper:
                    return txn_type
    
    # Fallback to pattern matching
    if 'OPENING' in particulars_upper:
        return 'OPENING'
    
    if 'CLOSING' in particulars_upper:
        return 'CLOSING'
    
    if 'CONT' in particulars_upper or 'CONTRIBUTION' in particulars_upper:
        return 'CONTRIBUTION'
    
    # Interest identification (broader detection)
    if 'INT' in particulars_upper or 'INTEREST' in particulars_upper:
        if 'INOPERATIVE' in particulars_upper:
            return 'INOPERATIVE_INTEREST'
        return 'INTEREST'
    
    # TRANSFER IN with INTEREST AMOUNT ONLY should be INTEREST
    if 'TRANSFER' in particulars_upper and 'IN' in particulars_upper and 'INTEREST' in particulars_upper:
        return 'INTEREST'
    
    if 'TDS' in particulars_upper:
        return 'TDS'
    
    if 'FINAL' in particulars_upper and 'SETTLEMENT' in particulars_upper:
        return 'FINAL_SETTLEMENT'
    
    if 'WITHDRAWAL' in particulars_upper:
        return 'WITHDRAWAL'
    
    if 'TRANSFER FROM' in particulars_upper:
        return 'TRANSFER_IN'
    
    if 'TRANSFER TO' in particulars_upper:
        return 'TRANSFER_OUT'
    
    if 'EDLI' in particulars_upper:
        return 'EDLI_CHARGES'
    
    if 'PENSION' in particulars_upper and 'REFUND' in particulars_upper:
        return 'PENSION_REFUND'
    
    return 'UNKNOWN'


def verify_transactions(transactions: List[Dict], opening_balance: Dict, closing_balance: Dict) -> List[Dict]:
    """
    Verify transactions against opening and closing balances
    
    Args:
        transactions: List of transaction dicts
        opening_balance: Dict with 'employee' and 'employer' opening balances
        closing_balance: Dict with 'employee' and 'employer' closing balances
        
    Returns:
        Updated transactions with verification notes
    """
    if not transactions:
        return transactions
    
    # Calculate total contributions from opening balance
    # Include ALL transactions including INTEREST as they represent actual credited amounts
    total_employee = Decimal(str(opening_balance.get('employee', 0)))
    total_employer = Decimal(str(opening_balance.get('employer', 0)))
    
    for txn in transactions:
        total_employee += Decimal(str(txn['employee_contribution']))
        total_employer += Decimal(str(txn['employer_contribution']))
    
    # Compare with closing balance
    expected_employee = closing_balance.get('employee', 0)
    expected_employer = closing_balance.get('employer', 0)
    
    employee_diff = abs(float(total_employee) - expected_employee)
    employer_diff = abs(float(total_employer) - expected_employer)
    
    # Add verification note to last transaction
    if transactions and (opening_balance.get('employee', 0) > 0 or opening_balance.get('employer', 0) > 0):
        notes = []
        if employee_diff > 0.01:
            notes.append(f"Employee: calculated ₹{float(total_employee):,.2f}, expected ₹{expected_employee:,.2f}, diff ₹{employee_diff:,.2f}")
        if employer_diff > 0.01:
            notes.append(f"Employer: calculated ₹{float(total_employer):,.2f}, expected ₹{expected_employer:,.2f}, diff ₹{employer_diff:,.2f}")
        
        if notes:
            transactions[-1]['notes'] = 'MISMATCH: ' + '; '.join(notes)
        else:
            transactions[-1]['notes'] = 'Balance verification: OK'
    
    return transactions


def clean_particulars(particulars: str) -> str:
    """
    Clean up particulars text (remove extra spaces, normalize)
    
    Args:
        particulars: Raw particulars text
        
    Returns:
        Cleaned text
    """
    if not particulars:
        return ''
    
    # Remove multiple spaces
    cleaned = ' '.join(particulars.split())
    
    # Remove leading/trailing punctuation
    cleaned = cleaned.strip('.,;:- ')
    
    return cleaned


def extract_pf_account_from_transfer(particulars: str) -> Optional[str]:
    """
    Extract PF account number from transfer particulars
    
    Args:
        particulars: Transaction particulars
        
    Returns:
        PF account number or None
    """
    # Pattern: XX/XXX/0000000/000/0000000
    match = re.search(r'([A-Z]{2}/[A-Z]{3}/\d+/\d+/\d+)', particulars)
    if match:
        return match.group(1)
    
    return None


def validate_transaction(txn: Dict) -> Tuple[bool, List[str]]:
    """
    Validate a single transaction
    
    Args:
        txn: Transaction dictionary
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Check date
    if not txn.get('date'):
        errors.append("Missing date")
    
    # Check transaction type
    if txn.get('transaction_type') == 'UNKNOWN':
        errors.append(f"Unknown transaction type: {txn.get('particulars')}")
    
    # Check amounts for contribution
    if txn['transaction_type'] == 'CONTRIBUTION':
        if txn['employee_contribution'] <= 0:
            errors.append("Contribution has zero/negative employee amount")
        if txn['employer_contribution'] < 0:
            errors.append("Contribution has negative employer amount")
    
    # Check withdrawal amounts
    if txn['transaction_type'] in ['WITHDRAWAL', 'FINAL_SETTLEMENT', 'TDS']:
        if txn['employee_contribution'] >= 0:
            errors.append("Withdrawal should have negative employee amount")
    
    # Check balance
    if txn['total_balance'] < 0:
        errors.append("Negative total balance")
    
    is_valid = len(errors) == 0
    return is_valid, errors


def format_date_for_csv(date_str: str) -> str:
    """
    Ensure date is in DD/MM/YYYY format for CSV output
    
    Args:
        date_str: Date string
        
    Returns:
        Formatted date string
    """
    if not date_str:
        return ''
    
    # Already in correct format
    if re.match(r'\d{2}/\d{2}/\d{4}', date_str):
        return date_str
    
    # Try to parse and reformat
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.strftime('%d/%m/%Y')
    except:
        return date_str


if __name__ == "__main__":
    # Test the parser
    import sys
    
    print("EPF Transaction Parser - Test Mode")
    print("=" * 60)
    
    # Test date parsing
    print("\nTesting date parsing:")
    test_dates = [
        "15/06/2024",
        "15-06-2024",
        "April 2024",
        "FY 2023-24",
        "31/03/2024"
    ]
    
    for date in test_dates:
        parsed = parse_epf_date(date)
        print(f"  {date:20s} -> {parsed}")
    
    # Test amount parsing
    print("\nTesting amount parsing:")
    test_amounts = [
        "1,25,000.50",
        "₹1,00,000",
        "(1,000.00)",
        "-5,000.00",
        "0.00"
    ]
    
    for amount in test_amounts:
        parsed = parse_indian_amount(amount)
        print(f"  {amount:20s} -> {parsed:,.2f}")
    
    # Test transaction classification
    print("\nTesting transaction classification:")
    test_particulars = [
        "CONT FOR APR 2024",
        "INT FOR FY 2023-24",
        "ADVANCE WITHDRAWAL",
        "TDS U/S 192A",
        "OPENING BALANCE"
    ]
    
    for particulars in test_particulars:
        txn_type = classify_transaction(particulars)
        print(f"  {particulars:30s} -> {txn_type}")
    
    print("\n" + "=" * 60)
    print("✅ Parser tests complete")
