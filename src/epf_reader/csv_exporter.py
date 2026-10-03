# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""
CSV Exporter Module
Export extracted EPF transaction data to CSV files
"""

import pandas as pd
import csv
import re
from pathlib import Path
from typing import List, Dict
from datetime import datetime


# Header fields masked when redaction is on. These names must match the keys
# pdf_analyzer.extract_header_info() actually produces — the list previously
# said 'pf_account' while the key is 'pf_account_number', so the PF account
# number was never redacted. tests/test_redaction.py pins the two together.
PII_HEADER_FIELDS = (
    'uan',
    'pf_account_number',
    'pf_account',           # tolerated alias
    'member_name',
    'father_husband_name',
    'establishment_name',
    'establishment_id',
    'dob',
    'doj_epf',
    'doj_employment',
    'address',
    'email',
    'phone',
)

# Header fields that carry no personal identifier and stay readable.
NON_PII_HEADER_FIELDS = (
    'statement_date',
)


def redact_pii(text: str, redact_type: str = 'REDACTED') -> str:
    """
    Redact personally identifiable information from text
    
    Args:
        text: Text to redact
        redact_type: Replacement text
        
    Returns:
        Redacted text
    """
    if not text or pd.isna(text):
        return text
    
    text = str(text)
    
    # Redact UAN (12-digit number)
    text = re.sub(r'\b\d{12}\b', redact_type, text)
    
    # Redact dates that look like DOB (DD-MM-YYYY, DD/MM/YYYY)
    text = re.sub(r'\b\d{2}[-/]\d{2}[-/]\d{4}\b', redact_type, text)
    
    # Redact email addresses
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', redact_type, text)
    
    # Redact phone numbers (10 digits, with optional +91, spaces, hyphens)
    text = re.sub(r'(?:\+91[-\s]?)?\d{10}', redact_type, text)
    text = re.sub(r'(?:\+91[-\s]?)?\d{5}[-\s]?\d{5}', redact_type, text)
    text = re.sub(r'\d{3}[-\s]?\d{3}[-\s]?\d{4}', redact_type, text)
    
    # Redact PAN (AAAAA9999A format)
    text = re.sub(r'\b[A-Z]{5}\d{4}[A-Z]\b', redact_type, text)
    
    # Redact Aadhaar (12 digits, often with spaces)
    text = re.sub(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', redact_type, text)
    
    return text


def redact_header_info(header_info: Dict, redact_pii_flag: bool = False) -> Dict:
    """
    Redact PII from header information
    
    Args:
        header_info: Header information dictionary
        redact_pii_flag: Whether to redact PII
        
    Returns:
        Redacted header info (or original if flag is False)
    """
    if not redact_pii_flag:
        return header_info
    
    redacted = header_info.copy()
    
    for field in PII_HEADER_FIELDS:
        if field in redacted and redacted[field]:
            redacted[field] = 'REDACTED'
    
    return redacted


def redact_transactions(transactions: List[Dict], redact_pii_flag: bool = False) -> List[Dict]:
    """
    Redact PII from transaction data
    
    Args:
        transactions: List of transaction dictionaries
        redact_pii_flag: Whether to redact PII
        
    Returns:
        Redacted transactions (or original if flag is False)
    """
    if not redact_pii_flag:
        return transactions
    
    redacted_txns = []
    for txn in transactions:
        redacted_txn = txn.copy()
        
        # Redact particulars field (may contain names, addresses)
        if 'particulars' in redacted_txn:
            redacted_txn['particulars'] = redact_pii(redacted_txn['particulars'])
        
        # Redact notes field
        if 'notes' in redacted_txn:
            redacted_txn['notes'] = redact_pii(redacted_txn['notes'])
        
        redacted_txns.append(redacted_txn)
    
    return redacted_txns


def export_to_csv(
    transactions: List[Dict],
    header_info: Dict,
    output_dir: str,
    base_filename: str = "epf_transactions",
    redact_pii_flag: bool = False
) -> Dict[str, str]:
    """
    Export transactions and metadata to CSV files
    
    Args:
        transactions: List of transaction dictionaries
        header_info: Header information dict
        output_dir: Output directory path
        base_filename: Base name for output files
        redact_pii_flag: Whether to redact personally identifiable information
        
    Returns:
        Dictionary with paths to created files
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Redact PII if requested
    if redact_pii_flag:
        transactions = redact_transactions(transactions, redact_pii_flag)
        header_info = redact_header_info(header_info, redact_pii_flag)
    
    # Generate output file paths
    transactions_file = output_path / f"{base_filename}.csv"
    metadata_file = output_path / f"{base_filename}_metadata.csv"
    summary_file = output_path / f"{base_filename}_summary.txt"
    
    # Export main transactions
    export_transactions_csv(transactions, transactions_file)
    
    # Export metadata
    export_metadata_csv(header_info, metadata_file)
    
    # Generate summary report
    summary = generate_summary_report(transactions, header_info)
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(summary)
    
    return {
        'transactions': str(transactions_file),
        'metadata': str(metadata_file),
        'summary': str(summary_file)
    }


def export_transactions_csv(transactions: List[Dict], output_file: Path):
    """
    Export transactions to CSV with proper formatting
    
    Args:
        transactions: List of transaction dictionaries
        output_file: Path to output CSV file
    """
    if not transactions:
        print("Warning: No transactions to export")
        return
    
    # Column order. 'direction' carries the passbook's own CR/DR marker, so a
    # negative amount can be traced back to the row that declared it a debit.
    columns = [
        'date',
        'particulars',
        'transaction_type',
        'direction',
        'employee_contribution',
        'employer_contribution',
        'total_contribution',
        'notes'
    ]
    
    # Calculate total_contribution for each transaction
    for txn in transactions:
        txn['total_contribution'] = txn.get('employee_contribution', 0) + txn.get('employer_contribution', 0)
    
    # Create DataFrame
    df = pd.DataFrame(transactions)
    
    # Ensure all columns exist
    for col in columns:
        if col not in df.columns:
            df[col] = ''
    
    # Select and order columns
    df = df[columns]
    
    # Format amounts to 2 decimal places
    amount_cols = [
        'employee_contribution', 'employer_contribution', 'pension_contribution',
        'employee_balance', 'employer_balance', 'pension_balance', 'total_balance'
    ]
    
    for col in amount_cols:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "0.00")
    
    # Export to CSV
    df.to_csv(output_file, index=False, encoding='utf-8')
    
    print(f"✅ Transactions exported: {output_file}")
    print(f"   Total rows: {len(df)}")


def export_metadata_csv(header_info: Dict, output_file: Path):
    """
    Export header metadata to CSV
    
    Args:
        header_info: Header information dictionary
        output_file: Path to output CSV file
    """
    # Create metadata rows
    metadata = []
    
    field_mapping = {
        'uan': 'UAN',
        'pf_account_number': 'PF Account Number',
        'member_name': 'Member Name',
        'father_husband_name': "Father's/Husband's Name",
        'dob': 'Date of Birth',
        'doj_epf': 'Date of Joining EPF',
        'doj_employment': 'Date of Joining Employment',
        'establishment_name': 'Establishment Name',
        'establishment_id': 'Establishment ID',
        'statement_date': 'Statement Date'
    }
    
    for key, label in field_mapping.items():
        value = header_info.get(key, '')
        if value:
            metadata.append({'Field': label, 'Value': value})
    
    # Add extraction date
    metadata.append({
        'Field': 'Extraction Date',
        'Value': datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    })
    
    # Create DataFrame and export
    df = pd.DataFrame(metadata)
    df.to_csv(output_file, index=False, encoding='utf-8')
    
    print(f"✅ Metadata exported: {output_file}")


def generate_summary_report(transactions: List[Dict], header_info: Dict) -> str:
    """
    Generate summary report text
    
    Args:
        transactions: List of transactions
        header_info: Header information
        
    Returns:
        Formatted summary report string
    """
    report = []
    report.append("=" * 80)
    report.append("EPF PASSBOOK EXTRACTION SUMMARY")
    report.append("=" * 80)
    report.append("")
    
    # Member information
    report.append("MEMBER INFORMATION:")
    report.append("-" * 80)
    report.append(f"UAN: {header_info.get('uan', 'N/A')}")
    report.append(f"PF Account: {header_info.get('pf_account_number', 'N/A')}")
    report.append(f"Name: {header_info.get('member_name', 'N/A')}")
    report.append(f"Establishment: {header_info.get('establishment_name', 'N/A')}")
    report.append("")
    
    # Transaction statistics
    report.append("TRANSACTION STATISTICS:")
    report.append("-" * 80)
    report.append(f"Total Transactions: {len(transactions)}")
    
    # Count by type
    type_counts = {}
    for txn in transactions:
        txn_type = txn.get('transaction_type', 'UNKNOWN')
        type_counts[txn_type] = type_counts.get(txn_type, 0) + 1
    
    report.append("\nTransactions by Type:")
    for txn_type, count in sorted(type_counts.items()):
        report.append(f"  {txn_type:25s}: {count:4d}")
    
    report.append("")
    
    # Date range
    if transactions:
        dates = [txn['date'] for txn in transactions if txn.get('date')]
        if dates:
            date_objs = [datetime.strptime(d, '%d/%m/%Y') for d in dates]
            report.append(f"Date Range: {min(date_objs).strftime('%d/%m/%Y')} to {max(date_objs).strftime('%d/%m/%Y')}")
    
    report.append("")
    
    # Financial summary
    report.append("FINANCIAL SUMMARY:")
    report.append("-" * 80)
    
    # Calculate totals
    total_employee_contrib = sum(
        txn['employee_contribution']
        for txn in transactions
        if txn.get('transaction_type') == 'CONTRIBUTION'
    )
    
    total_employer_contrib = sum(
        txn['employer_contribution']
        for txn in transactions
        if txn.get('transaction_type') == 'CONTRIBUTION'
    )
    
    total_interest = sum(
        txn['employee_contribution'] + txn['employer_contribution']
        for txn in transactions
        if txn.get('transaction_type') in ['INTEREST', 'INOPERATIVE_INTEREST']
    )
    
    total_withdrawals = abs(sum(
        txn['employee_contribution'] + txn['employer_contribution']
        for txn in transactions
        if txn.get('transaction_type') in ['WITHDRAWAL', 'FINAL_SETTLEMENT']
    ))
    
    total_tds = abs(sum(
        txn['employee_contribution']
        for txn in transactions
        if txn.get('transaction_type') == 'TDS'
    ))
    
    report.append(f"Total Employee Contributions: ₹{total_employee_contrib:,.2f}")
    report.append(f"Total Employer Contributions: ₹{total_employer_contrib:,.2f}")
    report.append(f"Total Contributions:          ₹{total_employee_contrib + total_employer_contrib:,.2f}")
    report.append("")
    report.append(f"Total Interest Earned:        ₹{total_interest:,.2f}")
    report.append(f"Total Withdrawals:            ₹{total_withdrawals:,.2f}")
    report.append(f"Total TDS Deducted:           ₹{total_tds:,.2f}")
    report.append("")
    
    report.append("")
    report.append("=" * 80)
    report.append(f"Report Generated: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    report.append("=" * 80)
    
    return "\n".join(report)


def export_debug_data(raw_tables: List[pd.DataFrame], output_dir: str, prefix: str = "debug"):
    """
    Export raw extracted tables for debugging
    
    Args:
        raw_tables: List of raw DataFrames
        output_dir: Output directory
        prefix: Prefix for debug files
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    for idx, df in enumerate(raw_tables):
        debug_file = output_path / f"{prefix}_table_{idx+1}.csv"
        df.to_csv(debug_file, index=False)
        print(f"Debug table exported: {debug_file}")


def create_excel_output(
    transactions: List[Dict],
    header_info: Dict,
    output_file: str
):
    """
    Create Excel file with multiple sheets (transactions, metadata, summary)
    
    Args:
        transactions: List of transactions
        header_info: Header information
        output_file: Path to output Excel file
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        
        # Create DataFrames
        df_transactions = pd.DataFrame(transactions)
        df_metadata = pd.DataFrame([
            {'Field': k, 'Value': v}
            for k, v in header_info.items()
            if v
        ])
        
        # Write to Excel
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            df_transactions.to_excel(writer, sheet_name='Transactions', index=False)
            df_metadata.to_excel(writer, sheet_name='Metadata', index=False)
            
            # Access workbook for formatting
            workbook = writer.book
            
            # Format transactions sheet
            ws_txn = workbook['Transactions']
            
            # Bold headers
            for cell in ws_txn[1]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
            
            # Auto-adjust column widths
            for column in ws_txn.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws_txn.column_dimensions[column_letter].width = adjusted_width
        
        print(f"✅ Excel file created: {output_file}")
        
    except ImportError:
        print("⚠️  openpyxl not installed. Skipping Excel export.")
        print("   Install with: pip install openpyxl")


if __name__ == "__main__":
    # Test CSV exporter
    import sys
    
    print("EPF CSV Exporter - Test Mode")
    print("=" * 70)
    
    # Create test data
    test_transactions = [
        {
            'date': '01/04/2023',
            'period': 'APR 2023',
            'particulars': 'CONT FOR APR 2023',
            'transaction_type': 'CONTRIBUTION',
            'employee_contribution': 2400.0,
            'employer_contribution': 2400.0,
            'pension_contribution': 1250.0,
            'employee_balance': 2400.0,
            'employer_balance': 2400.0,
            'pension_balance': 1250.0,
            'total_balance': 6050.0,
            'notes': ''
        },
        {
            'date': '31/03/2024',
            'period': 'FY 2023-24',
            'particulars': 'INT FOR FY 2023-24',
            'transaction_type': 'INTEREST',
            'employee_contribution': 204.0,
            'employer_contribution': 204.0,
            'pension_contribution': 106.25,
            'employee_balance': 2604.0,
            'employer_balance': 2604.0,
            'pension_balance': 1356.25,
            'total_balance': 6564.25,
            'notes': ''
        }
    ]
    
    test_header = {
        'uan': '100123456789',
        'pf_account_number': 'KN/BNG/0012345/000/1234567',
        'member_name': 'TEST USER',
        'establishment_name': 'TEST COMPANY PVT LTD'
    }
    
    # Export to current directory
    output_dir = "test_output"
    
    print(f"\nExporting to: {output_dir}/")
    files = export_to_csv(test_transactions, test_header, output_dir, "test_epf")
    
    print("\nGenerated files:")
    for file_type, file_path in files.items():
        print(f"  {file_type}: {file_path}")
    
    print("\n✅ Export test complete")
