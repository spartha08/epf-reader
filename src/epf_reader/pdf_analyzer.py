# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""
PDF Analyzer Module
Analyzes EPF passbook PDFs to determine type (text-based vs scanned) and extracts header information
"""

import re
from pypdf import PdfReader
import pdfplumber
from pathlib import Path
from typing import Dict, Optional, Tuple


def analyze_pdf(pdf_path: str) -> Dict:
    """
    Analyze EPF passbook PDF to determine best extraction method and extract metadata
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Dictionary with analysis results:
        - method: 'tabula', 'camelot', or 'ocr'
        - pages: Total page count
        - header: Dict with UAN, PF Account, Name, etc.
        - is_text_based: Boolean indicating if PDF has selectable text
        - table_region: Estimated table boundaries
    """
    pdf_path = Path(pdf_path)
    
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    # Determine if text-based or scanned
    is_text_based = check_if_text_based(str(pdf_path))
    
    # Get page count
    page_count = get_page_count(str(pdf_path))
    
    # Extract header information
    header_info = extract_header_info(str(pdf_path))
    
    # Determine best extraction method.
    # For a text-based PDF this is pdfplumber: it needs no Java (tabula) or
    # Ghostscript (camelot), reads both bordered and borderless layouts via its
    # two table strategies, and is accurate because it reads the embedded text
    # rather than transcribing pixels. tabula/camelot stay available to request
    # explicitly. has_borders is kept for diagnostics, not for the choice —
    # pdfplumber tries the ruled-grid strategy first either way.
    has_borders = check_for_table_borders(str(pdf_path)) if is_text_based else False
    method = 'pdfplumber' if is_text_based else 'ocr'
    
    # Estimate table region (skip header and footer)
    table_region = estimate_table_region(page_count)
    
    return {
        'method': method,
        'pages': page_count,
        'header': header_info,
        'is_text_based': is_text_based,
        'has_borders': has_borders,
        'table_region': table_region,
        'pdf_path': str(pdf_path)
    }


def check_if_text_based(pdf_path: str) -> bool:
    """
    Check if PDF has selectable text (text-based) or is an image (scanned)
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        True if text-based, False if scanned/image
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Check first page for text
            first_page = pdf.pages[0]
            text = first_page.extract_text()
            
            # If we got substantial text, it's text-based
            if text and len(text.strip()) > 100:
                return True
            
            # Check if page has text objects
            if first_page.chars and len(first_page.chars) > 50:
                return True
                
    except Exception as e:
        print(f"Error checking PDF type: {e}")
    
    return False


def get_page_count(pdf_path: str) -> int:
    """Get total number of pages in PDF"""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PdfReader(file)
            return len(pdf_reader.pages)
    except Exception as e:
        print(f"Error getting page count: {e}")
        return 0


def extract_header_info(pdf_path: str, page: int = 0) -> Dict:
    """
    Extract header information from EPF passbook (UAN, PF Account, Name, etc.)
    
    Args:
        pdf_path: Path to PDF file
        page: Page number to extract from (default: first page)
        
    Returns:
        Dictionary with header fields
    """
    header_info = {
        'uan': None,
        'pf_account_number': None,
        'member_name': None,
        'father_husband_name': None,
        'dob': None,
        'doj_epf': None,
        'doj_employment': None,
        'establishment_name': None,
        'establishment_id': None,
        'statement_date': None
    }
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page >= len(pdf.pages):
                page = 0
            
            # Extract text from first page
            text = pdf.pages[page].extract_text()
            
            if not text:
                return header_info
            
            # Extract UAN (12 digits)
            uan_match = re.search(r'UAN\s*:?\s*(\d{12})', text, re.IGNORECASE)
            if uan_match:
                header_info['uan'] = uan_match.group(1)
            
            # Extract PF Account Number (format: XX/XXX/0000000/000/0000000)
            pf_match = re.search(
                r'PF\s+ACCOUNT\s+NUMBER\s*:?\s*([A-Z]{2}/[A-Z]{3}/\d+/\d+/\d+)',
                text,
                re.IGNORECASE
            )
            if pf_match:
                header_info['pf_account_number'] = pf_match.group(1)
            
            # Extract Member Name (typically all caps)
            name_match = re.search(
                r'MEMBER\s+NAME\s*:?\s*([A-Z\s.]+?)(?:\n|(?:FATHER|HUSBAND|DATE|DOB))',
                text,
                re.IGNORECASE
            )
            if name_match:
                header_info['member_name'] = name_match.group(1).strip()
            
            # Extract Father's/Husband's Name
            father_match = re.search(
                r'(?:FATHER|HUSBAND)(?:\'?S)?\s+NAME\s*:?\s*([A-Z\s.]+?)(?:\n|DATE|DOB)',
                text,
                re.IGNORECASE
            )
            if father_match:
                header_info['father_husband_name'] = father_match.group(1).strip()
            
            # Extract Date of Birth
            dob_match = re.search(
                r'DATE\s+OF\s+BIRTH\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})',
                text,
                re.IGNORECASE
            )
            if dob_match:
                header_info['dob'] = dob_match.group(1)
            
            # Extract Date of Joining EPF
            doj_epf_match = re.search(
                r'DATE\s+OF\s+JOINING\s+EPF\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})',
                text,
                re.IGNORECASE
            )
            if doj_epf_match:
                header_info['doj_epf'] = doj_epf_match.group(1)
            
            # Extract Date of Joining Employment
            doj_emp_match = re.search(
                r'DATE\s+OF\s+JOINING\s+EMPLOYMENT\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})',
                text,
                re.IGNORECASE
            )
            if doj_emp_match:
                header_info['doj_employment'] = doj_emp_match.group(1)
            
            # Extract Establishment Name (multi-word, may span lines)
            est_name_match = re.search(
                r'ESTABLISHMENT\s+NAME\s*:?\s*([A-Z0-9\s&.,-]+?)(?:\n\s*ESTABLISHMENT\s+ID|$)',
                text,
                re.IGNORECASE | re.DOTALL
            )
            if est_name_match:
                # Clean up the name (remove extra whitespace)
                est_name = ' '.join(est_name_match.group(1).split())
                header_info['establishment_name'] = est_name.strip()
            
            # Extract Establishment ID
            est_id_match = re.search(
                r'ESTABLISHMENT\s+ID\s*:?\s*([A-Z]{2}/[A-Z]{3}/\d+)',
                text,
                re.IGNORECASE
            )
            if est_id_match:
                header_info['establishment_id'] = est_id_match.group(1)
            
            # Extract statement generation date
            gen_date_match = re.search(
                r'GENERATED\s+ON\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})',
                text,
                re.IGNORECASE
            )
            if gen_date_match:
                header_info['statement_date'] = gen_date_match.group(1)
                
    except Exception as e:
        print(f"Error extracting header info: {e}")
    
    return header_info


def check_for_table_borders(pdf_path: str, page: int = 0) -> bool:
    """
    Check if PDF tables have visible borders (better for Camelot)
    
    Args:
        pdf_path: Path to PDF file
        page: Page number to check
        
    Returns:
        True if borders detected, False otherwise
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page >= len(pdf.pages):
                page = 0
            
            # Check for line objects (borders)
            page_obj = pdf.pages[page]
            
            # Horizontal and vertical lines indicate borders
            h_lines = page_obj.edges
            
            # If we have substantial lines, assume bordered table
            if h_lines and len(h_lines) > 10:
                return True
                
    except Exception as e:
        print(f"Error checking for borders: {e}")
    
    return False


def estimate_table_region(page_count: int) -> Dict:
    """
    Estimate table region boundaries (to skip header/footer)
    
    Args:
        page_count: Total number of pages
        
    Returns:
        Dictionary with region boundaries (as fractions of page)
    """
    # Standard EPF passbook layout
    return {
        'top': 0.15,      # Skip header (15% from top)
        'bottom': 0.95,   # Skip footer (5% from bottom)
        'left': 0.05,     # 5% margin from left
        'right': 0.95     # 5% margin from right
    }


def validate_header_info(header_info: Dict) -> Tuple[bool, list]:
    """
    Validate extracted header information
    
    Args:
        header_info: Dictionary with header fields
        
    Returns:
        Tuple of (is_valid: bool, errors: list)
    """
    errors = []
    
    # Check critical fields
    if not header_info.get('uan'):
        errors.append("UAN not found")
    elif len(header_info['uan']) != 12:
        errors.append(f"Invalid UAN length: {header_info['uan']}")
    
    if not header_info.get('pf_account_number'):
        errors.append("PF Account Number not found")
    
    if not header_info.get('member_name'):
        errors.append("Member Name not found")
    
    is_valid = len(errors) == 0
    
    return is_valid, errors


if __name__ == "__main__":
    # Test the analyzer
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python pdf_analyzer.py <pdf_path>")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    
    print(f"Analyzing: {pdf_file}")
    print("=" * 60)
    
    analysis = analyze_pdf(pdf_file)
    
    print(f"Recommended method: {analysis['method']}")
    print(f"Total pages: {analysis['pages']}")
    print(f"Text-based: {analysis['is_text_based']}")
    print()
    print("Header Information:")
    print("-" * 60)
    
    for key, value in analysis['header'].items():
        if value:
            print(f"  {key}: {value}")
    
    print()
    is_valid, errors = validate_header_info(analysis['header'])
    
    if is_valid:
        print("✅ Header validation passed")
    else:
        print("❌ Header validation failed:")
        for error in errors:
            print(f"  - {error}")
