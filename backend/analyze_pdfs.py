"""
Script to analyze PDF structure for parser development
"""

import pdfplumber
import sys
from pathlib import Path


def analyze_pdf(pdf_path):
    """Analyze PDF structure and content"""
    print(f"\n{'='*60}")
    print(f"Analyzing: {Path(pdf_path).name}")
    print('='*60)

    with pdfplumber.open(pdf_path) as pdf:
        print(f"\nTotal pages: {len(pdf.pages)}")

        # Analyze first page
        page = pdf.pages[0]
        print(f"\nFirst Page Dimensions: {page.width} x {page.height}")

        # Extract text
        text = page.extract_text()
        print("\n--- First 1000 characters of text ---")
        print(text[:1000] if text else "No text found")

        # Extract tables
        tables = page.extract_tables()
        print(f"\n--- Tables found: {len(tables)} ---")

        if tables:
            print("\nFirst table preview (first 5 rows):")
            for i, row in enumerate(tables[0][:5]):
                print(f"Row {i}: {row}")

        # Look for keywords
        if text:
            text_lower = text.lower()
            print("\n--- Bank Detection ---")
            if 'maybank' in text_lower:
                print("✓ Maybank detected")
            if 'uob' in text_lower or 'united overseas bank' in text_lower:
                print("✓ UOB detected")
            if 'dbs' in text_lower or 'posb' in text_lower:
                print("✓ DBS/POSB detected")
            if 'ocbc' in text_lower:
                print("✓ OCBC detected")
            if 'citibank' in text_lower:
                print("✓ Citibank detected")

            print("\n--- Key Fields ---")
            if 'card' in text_lower:
                print("✓ Contains 'card'")
            if 'statement' in text_lower:
                print("✓ Contains 'statement'")
            if 'transaction' in text_lower:
                print("✓ Contains 'transaction'")


if __name__ == "__main__":
    # Analyze all statement PDFs
    statements_dir = Path("../statements")

    # Maybank
    maybank_dir = statements_dir / "maybank"
    if maybank_dir.exists():
        for pdf_file in maybank_dir.glob("*.pdf"):
            analyze_pdf(pdf_file)

    # UOB
    uob_dir = statements_dir / "uob"
    if uob_dir.exists():
        for pdf_file in uob_dir.glob("*.pdf"):
            analyze_pdf(pdf_file)
