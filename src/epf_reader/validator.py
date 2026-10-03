# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""
Validator Module
Validate extracted EPF transaction data for accuracy and consistency
"""

import pandas as pd
from typing import List, Dict, Tuple
from datetime import datetime
from decimal import Decimal


def validate_transactions(transactions: List[Dict], header_info: Dict) -> Tuple[bool, List[str], List[str]]:
    """
    Comprehensive validation of extracted transactions
    
    Args:
        transactions: List of transaction dictionaries
        header_info: Header information from PDF
        
    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    errors = []
    warnings = []
    
    if not transactions:
        errors.append("No transactions found")
        return False, errors, warnings
    
    # Validate header information
    header_errors = validate_header(header_info)
    if header_errors:
        warnings.extend([f"Header: {err}" for err in header_errors])
    
    # Validate date sequence
    date_errors = validate_date_sequence(transactions)
    if date_errors:
        errors.extend(date_errors)
    
    # Validate individual transactions
    for idx, txn in enumerate(transactions):
        txn_errors = validate_single_transaction(txn, idx)
        if txn_errors:
            errors.extend(txn_errors)
    
    # Validate transaction types
    type_warnings = validate_transaction_types(transactions)
    warnings.extend(type_warnings)
    
    # Validate amount ranges
    amount_warnings = validate_amount_ranges(transactions)
    warnings.extend(amount_warnings)
    
    # Check for missing periods
    missing_periods = detect_missing_periods(transactions)
    if missing_periods:
        warnings.extend([f"Possible missing period: {period}" for period in missing_periods])
    
    is_valid = len(errors) == 0
    
    return is_valid, errors, warnings


def validate_header(header_info: Dict) -> List[str]:
    """Validate header information"""
    errors = []
    
    if not header_info.get('uan'):
        errors.append("UAN not found")
    elif len(str(header_info['uan'])) != 12:
        errors.append(f"Invalid UAN: {header_info['uan']}")
    
    if not header_info.get('pf_account_number'):
        errors.append("PF Account Number not found")
    
    if not header_info.get('member_name'):
        errors.append("Member Name not found")
    
    return errors


def validate_date_sequence(transactions: List[Dict]) -> List[str]:
    """
    Validate that dates are in chronological order
    
    Args:
        transactions: List of transactions
        
    Returns:
        List of error messages
    """
    errors = []
    
    prev_date = None
    for idx, txn in enumerate(transactions):
        date_str = txn.get('date')
        
        if not date_str:
            errors.append(f"Row {idx}: Missing date")
            continue
        
        try:
            # Parse date
            current_date = datetime.strptime(date_str, '%d/%m/%Y')
            
            # Check chronological order
            if prev_date and current_date < prev_date:
                errors.append(
                    f"Row {idx}: Date out of order - {date_str} comes after "
                    f"{prev_date.strftime('%d/%m/%Y')}"
                )
            
            prev_date = current_date
            
        except ValueError:
            errors.append(f"Row {idx}: Invalid date format - {date_str}")
    
    return errors


def validate_single_transaction(txn: Dict, idx: int) -> List[str]:
    """
    Validate a single transaction
    
    Args:
        txn: Transaction dictionary
        idx: Transaction index
        
    Returns:
        List of error messages
    """
    errors = []
    
    txn_type = txn.get('transaction_type', 'UNKNOWN')
    date = txn.get('date', 'unknown')
    
    # Validate contribution transactions
    if txn_type == 'CONTRIBUTION':
        if txn['employee_contribution'] <= 0:
            errors.append(
                f"Row {idx} ({date}): Contribution has zero/negative employee amount"
            )
        
        # Employer should be non-negative
        if txn['employer_contribution'] < 0:
            errors.append(
                f"Row {idx} ({date}): Contribution has negative employer amount"
            )
    
    # Validate withdrawal/TDS transactions
    if txn_type in ['WITHDRAWAL', 'FINAL_SETTLEMENT', 'TDS']:
        # At least one amount should be negative (debit)
        total_debit = (
            txn['employee_contribution'] +
            txn['employer_contribution']
        )
        
        if total_debit >= 0:
            errors.append(
                f"Row {idx} ({date}): {txn_type} should have negative amounts (debit)"
            )
    
    # Validate interest transactions
    if txn_type in ['INTEREST', 'INOPERATIVE_INTEREST']:
        # Interest should be positive (credit)
        if txn['employee_contribution'] < 0:
            errors.append(
                f"Row {idx} ({date}): Interest should be positive (credit)"
            )
    
    return errors


def validate_transaction_types(transactions: List[Dict]) -> List[str]:
    """
    Validate transaction type distribution
    
    Args:
        transactions: List of transactions
        
    Returns:
        List of warning messages
    """
    warnings = []
    
    # Count transaction types
    type_counts = {}
    for txn in transactions:
        txn_type = txn.get('transaction_type', 'UNKNOWN')
        type_counts[txn_type] = type_counts.get(txn_type, 0) + 1
    
    # Check for unknown transactions
    unknown_count = type_counts.get('UNKNOWN', 0)
    if unknown_count > 0:
        warnings.append(
            f"Found {unknown_count} transactions with unknown type "
            f"({unknown_count/len(transactions)*100:.1f}%)"
        )
    
    # Check for expected transaction types
    if 'CONTRIBUTION' not in type_counts:
        warnings.append("No contribution transactions found")
    
    return warnings


def validate_amount_ranges(transactions: List[Dict]) -> List[str]:
    """
    Validate that amounts are within reasonable ranges
    
    Args:
        transactions: List of transactions
        
    Returns:
        List of warning messages
    """
    warnings = []
    
    # Reasonable limits (adjust based on actual EPF data)
    MAX_MONTHLY_CONTRIBUTION = 100000.0  # ₹1 lakh per month
    MAX_ANNUAL_INTEREST = 1000000.0      # ₹10 lakhs annual interest
    MAX_WITHDRAWAL = 10000000.0          # ₹1 crore withdrawal
    
    for idx, txn in enumerate(transactions):
        txn_type = txn.get('transaction_type')
        date = txn.get('date', 'unknown')
        
        # Check contribution amounts
        if txn_type == 'CONTRIBUTION':
            if abs(txn['employee_contribution']) > MAX_MONTHLY_CONTRIBUTION:
                warnings.append(
                    f"Row {idx} ({date}): Unusually large contribution - "
                    f"₹{abs(txn['employee_contribution']):,.2f}"
                )
        
        # Check interest amounts
        if txn_type in ['INTEREST', 'INOPERATIVE_INTEREST']:
            total_interest = (
                txn['employee_contribution'] +
                txn['employer_contribution']
            )
            if abs(total_interest) > MAX_ANNUAL_INTEREST:
                warnings.append(
                    f"Row {idx} ({date}): Unusually large interest - "
                    f"₹{abs(total_interest):,.2f}"
                )
        
        # Check withdrawal amounts
        if txn_type in ['WITHDRAWAL', 'FINAL_SETTLEMENT']:
            total_withdrawal = abs(
                txn['employee_contribution'] +
                txn['employer_contribution']
            )
            if total_withdrawal > MAX_WITHDRAWAL:
                warnings.append(
                    f"Row {idx} ({date}): Unusually large withdrawal - "
                    f"₹{total_withdrawal:,.2f}"
                )
    
    return warnings


def detect_missing_periods(transactions: List[Dict]) -> List[str]:
    """
    Detect potentially missing periods (gaps in contributions)
    
    Args:
        transactions: List of transactions
        
    Returns:
        List of missing period strings
    """
    missing = []
    
    # Extract contribution transactions
    contributions = [
        txn for txn in transactions
        if txn.get('transaction_type') == 'CONTRIBUTION'
    ]
    
    if len(contributions) < 2:
        return missing
    
    # Sort by date
    contributions.sort(key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))
    
    # Check for gaps (more than 2 months)
    for i in range(len(contributions) - 1):
        current_date = datetime.strptime(contributions[i]['date'], '%d/%m/%Y')
        next_date = datetime.strptime(contributions[i+1]['date'], '%d/%m/%Y')
        
        # Calculate month difference
        month_diff = (next_date.year - current_date.year) * 12 + (next_date.month - current_date.month)
        
        if month_diff > 2:
            missing.append(
                f"Gap of {month_diff-1} month(s) between "
                f"{current_date.strftime('%b %Y')} and {next_date.strftime('%b %Y')}"
            )
    
    return missing


def generate_validation_report(is_valid: bool, errors: List[str], warnings: List[str]) -> str:
    """
    Generate human-readable validation report
    
    Args:
        is_valid: Whether validation passed
        errors: List of errors
        warnings: List of warnings
        
    Returns:
        Formatted report string
    """
    report = []
    report.append("=" * 70)
    report.append("EPF Transaction Validation Report")
    report.append("=" * 70)
    report.append("")
    
    if is_valid:
        report.append("✅ VALIDATION PASSED")
    else:
        report.append("❌ VALIDATION FAILED")
    
    report.append("")
    report.append(f"Errors: {len(errors)}")
    report.append(f"Warnings: {len(warnings)}")
    report.append("")
    
    if errors:
        report.append("ERRORS:")
        report.append("-" * 70)
        for error in errors:
            report.append(f"  ❌ {error}")
        report.append("")
    
    if warnings:
        report.append("WARNINGS:")
        report.append("-" * 70)
        for warning in warnings:
            report.append(f"  ⚠️  {warning}")
        report.append("")
    
    report.append("=" * 70)
    
    return "\n".join(report)


if __name__ == "__main__":
    # Test validator
    print("EPF Transaction Validator - Test Mode")
    print("=" * 70)
    
    # Create test transactions
    test_transactions = [
        {
            'date': '01/04/2023',
            'period': 'APR 2023',
            'particulars': 'CONT FOR APR 2023',
            'transaction_type': 'CONTRIBUTION',
            'employee_contribution': 2400.0,
            'employer_contribution': 2400.0,
            'pension_contribution': 1250.0,
            'total_balance': 6050.0
        },
        {
            'date': '31/03/2024',
            'period': 'FY 2023-24',
            'particulars': 'INT FOR FY 2023-24',
            'transaction_type': 'INTEREST',
            'employee_contribution': 2040.0,
            'employer_contribution': 2040.0,
            'pension_contribution': 1062.5,
            'total_balance': 11192.5
        }
    ]
    
    test_header = {
        'uan': '100123456789',
        'pf_account_number': 'KN/BNG/0012345/000/1234567',
        'member_name': 'TEST USER'
    }
    
    # Run validation
    is_valid, errors, warnings = validate_transactions(test_transactions, test_header)
    
    # Print report
    report = generate_validation_report(is_valid, errors, warnings)
    print(report)
