#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""
EPF Passbook OCR Extractor
Main CLI interface for extracting EPF transaction data from PDF to CSV
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

from .pdf_analyzer import analyze_pdf
from .table_extractor import extract_tables, clean_extracted_tables, merge_multi_page_tables
from .transaction_parser import parse_transactions, verify_transactions
from .validator import validate_transactions, generate_validation_report
from .csv_exporter import export_to_csv, export_debug_data


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Extract EPF passbook transaction data from PDF to CSV',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Basic usage (auto-detect method)
  python main.py --input epf_passbook.pdf --output-dir output/

  # Force OCR for scanned PDF
  python main.py --input scanned.pdf --output-dir output/ --method ocr

  # Enable debug mode with raw table export
  python main.py --input passbook.pdf --output-dir output/ --debug

  # Specify custom output filename
  python main.py --input passbook.pdf --output-dir output/ --output my_epf_data

Extraction Methods:
  auto       - Automatically select best method (default)
  pdfplumber - Read the embedded text layer (default for text PDFs; no Java/OCR)
  tabula     - Use Tabula-py for text-based PDFs (needs Java)
  camelot    - Use Camelot-py for bordered tables (needs Ghostscript)
  ocr        - Use Tesseract-OCR for scanned PDFs (slowest)
        '''
    )
    
    # Required arguments
    parser.add_argument(
        '--input', '-i',
        required=True,
        help='Path to EPF passbook PDF file'
    )
    
    parser.add_argument(
        '--output-dir', '-o',
        required=True,
        help='Directory for output CSV files'
    )
    
    # Optional arguments
    parser.add_argument(
        '--output', '-n',
        default='epf_transactions',
        help='Base name for output files (default: epf_transactions)'
    )
    
    parser.add_argument(
        '--method', '-m',
        choices=['auto', 'pdfplumber', 'tabula', 'camelot', 'ocr'],
        default='auto',
        help='Extraction method (default: auto)'
    )
    
    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug mode (saves raw extracted tables)'
    )
    
    parser.add_argument(
        '--no-validate',
        action='store_true',
        help='Skip validation step'
    )
    
    parser.add_argument(
        '--excel',
        action='store_true',
        help='Also generate Excel output (requires openpyxl)'
    )
    
    parser.add_argument(
        '--no-redact-pii',
        action='store_true',
        help='Do NOT redact personally identifiable information (UAN, DOB, names, addresses, email, phone). By default, PII is redacted.'
    )
    
    args = parser.parse_args()
    
    # Run extraction pipeline
    try:
        process_epf_passbook(
            pdf_path=args.input,
            output_dir=args.output_dir,
            output_name=args.output,
            method=args.method,
            debug=args.debug,
            validate=not args.no_validate,
            excel=args.excel,
            redact_pii=not args.no_redact_pii
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def process_epf_passbook(
    pdf_path: str,
    output_dir: str,
    output_name: str = 'epf_transactions',
    method: str = 'auto',
    debug: bool = False,
    validate: bool = True,
    excel: bool = False,
    redact_pii: bool = True
):
    """
    Complete EPF passbook extraction pipeline
    
    Args:
        pdf_path: Path to PDF file
        output_dir: Output directory
        output_name: Base filename for outputs
        method: Extraction method
        debug: Enable debug mode
        validate: Run validation
        excel: Generate Excel output
        redact_pii: Redact personally identifiable information (default: True)
    """
    print("=" * 80)
    print("EPF PASSBOOK OCR EXTRACTOR")
    print("=" * 80)
    print()
    
    # Create the output directory up front. export_to_csv() creates it too, but
    # that is step 7 — the validation report in step 6 is written first, so a
    # not-yet-existing --output-dir crashed the run after all the work was done.
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Step 1: Analyze PDF
    print("Step 1: Analyzing PDF...")
    print("-" * 80)
    
    analysis = analyze_pdf(pdf_path)
    
    print(f"  PDF Type: {'Text-based' if analysis['is_text_based'] else 'Scanned/Image'}")
    print(f"  Pages: {analysis['pages']}")
    print(f"  Recommended Method: {analysis['method']}")
    print()
    
    # Print header info
    print("  Header Information:")
    for key, value in analysis['header'].items():
        if value:
            print(f"    {key}: {value}")
    print()
    
    # Step 2: Extract tables
    print("Step 2: Extracting tables...")
    print("-" * 80)
    
    raw_tables = extract_tables(pdf_path, analysis, method=method)
    
    if not raw_tables:
        print("❌ No tables extracted from PDF")
        sys.exit(1)
    
    print(f"  Extracted {len(raw_tables)} table(s)")
    print()
    
    # Save debug tables if requested
    if debug:
        export_debug_data(raw_tables, output_dir, prefix=f"{output_name}_debug")
    
    # Step 3: Clean and merge tables
    print("Step 3: Cleaning and merging tables...")
    print("-" * 80)
    
    cleaned_tables, balance_metadata = clean_extracted_tables(raw_tables)
    
    if not cleaned_tables:
        print("❌ No valid data in extracted tables")
        sys.exit(1)
    
    merged_table = merge_multi_page_tables(cleaned_tables)
    print(f"  Rows after cleaning: {len(merged_table)}")
    print()
    
    # Step 4: Parse transactions
    print("Step 4: Parsing transactions...")
    print("-" * 80)
    
    transactions = parse_transactions(merged_table)
    
    # Add interest transactions from metadata
    for interest_row in balance_metadata.get('interest_rows', []):
        transactions.append({
            'date': interest_row['date'],
            'particulars': interest_row['particulars'],
            'transaction_type': 'INTEREST',
            'employee_contribution': interest_row['employee'],
            'employer_contribution': interest_row['employer'],
            'notes': 'Interest credited'
        })
    
    # Sort transactions by date
    if transactions:
        transactions.sort(key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))
    
    if not transactions:
        print("❌ No transactions parsed")
        sys.exit(1)
    
    print(f"  Parsed {len(transactions)} transactions")
    
    # Count by type
    type_counts = {}
    for txn in transactions:
        txn_type = txn.get('transaction_type', 'UNKNOWN')
        type_counts[txn_type] = type_counts.get(txn_type, 0) + 1
    
    print("  Transaction types:")
    for txn_type, count in sorted(type_counts.items()):
        print(f"    {txn_type}: {count}")
    print()
    
    # Step 5: Verify transactions against opening/closing balances
    print("Step 5: Verifying transactions against opening/closing balances...")
    print("-" * 80)
    
    opening = balance_metadata.get('opening_balance', {})
    closing = balance_metadata.get('closing_balance', {})
    
    print(f"  Opening Balance (as on {opening.get('date', 'N/A')}):")
    print(f"    Employee: ₹{opening.get('employee', 0):,.2f}")
    print(f"    Employer: ₹{opening.get('employer', 0):,.2f}")
    print(f"    Total:    ₹{opening.get('employee', 0) + opening.get('employer', 0):,.2f}")
    print()
    print(f"  Closing Balance (as on {closing.get('date', 'N/A')}):")
    print(f"    Employee: ₹{closing.get('employee', 0):,.2f}")
    print(f"    Employer: ₹{closing.get('employer', 0):,.2f}")
    print(f"    Total:    ₹{closing.get('employee', 0) + closing.get('employer', 0):,.2f}")
    
    transactions = verify_transactions(transactions, opening, closing)
    
    if transactions and transactions[-1].get('notes'):
        print(f"\n  Verification: {transactions[-1]['notes']}")
    print()
    
    # Step 6: Validate (optional)
    if validate:
        print("Step 6: Validating data...")
        print("-" * 80)
        
        is_valid, errors, warnings = validate_transactions(transactions, analysis['header'])
        
        if is_valid:
            print("  ✅ Validation passed")
        else:
            print(f"  ❌ Validation failed with {len(errors)} error(s)")
        
        if warnings:
            print(f"  ⚠️  {len(warnings)} warning(s)")
        
        # Print first few errors/warnings
        if errors:
            print("\n  Errors:")
            for error in errors[:5]:
                print(f"    • {error}")
            if len(errors) > 5:
                print(f"    ... and {len(errors)-5} more")
        
        if warnings:
            print("\n  Warnings:")
            for warning in warnings[:5]:
                print(f"    • {warning}")
            if len(warnings) > 5:
                print(f"    ... and {len(warnings)-5} more")
        
        print()
        
        # Save validation report
        validation_report = generate_validation_report(is_valid, errors, warnings)
        report_file = Path(output_dir) / f"{output_name}_validation.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(validation_report)
        print(f"  Validation report saved: {report_file}")
        print()
    
    # Step 7: Export to CSV
    print(f"Step {'7' if validate else '6'}: Exporting to CSV...")
    print("-" * 80)
    
    output_files = export_to_csv(
        transactions,
        analysis['header'],
        output_dir,
        output_name,
        redact_pii_flag=redact_pii
    )
    
    print()
    print("  Generated files:")
    for file_type, file_path in output_files.items():
        print(f"    {file_type}: {file_path}")
    print()
    
    # Step 8: Export to Excel (optional)
    if excel:
        print("Step 8: Exporting to Excel...")
        print("-" * 80)
        
        try:
            from .csv_exporter import create_excel_output
            excel_file = Path(output_dir) / f"{output_name}.xlsx"
            create_excel_output(transactions, analysis['header'], str(excel_file))
            print(f"  Excel file: {excel_file}")
            print()
        except Exception as e:
            print(f"  ⚠️  Excel export failed: {e}")
            print()
    
    # Summary
    print("=" * 80)
    print("✅ EXTRACTION COMPLETE")
    print("=" * 80)
    print()
    print(f"Total transactions: {len(transactions)}")
    print(f"Opening balance: ₹{opening.get('employee', 0) + opening.get('employer', 0):,.2f}")
    print(f"Closing balance: ₹{closing.get('employee', 0) + closing.get('employer', 0):,.2f}")
    
    print()
    print("Next steps:")
    print(f"  1. Review the transactions CSV: {output_files['transactions']}")
    print(f"  2. Check the summary report: {output_files['summary']}")
    if validate:
        print(f"  3. Review validation report: {Path(output_dir) / f'{output_name}_validation.txt'}")
    print()


if __name__ == "__main__":
    main()
