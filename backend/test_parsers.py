"""
Test script to validate all PDF parsers with example statements.
"""

from pathlib import Path
from app.parsers.factory import ParserFactory


def test_parser(pdf_path: Path):
    """Test a single PDF file"""
    print(f"\n{'='*80}")
    print(f"Testing: {pdf_path.name}")
    print('='*80)

    # Detect bank
    bank = ParserFactory.detect_bank(str(pdf_path))
    print(f"Detected Bank: {bank.upper() if bank else 'UNKNOWN'}")

    # Parse statement
    parsed_data = ParserFactory.parse(str(pdf_path))

    if not parsed_data:
        print("❌ FAILED: Could not parse statement")
        return False

    # Display results
    print(f"\n✅ Successfully parsed!")
    print(f"\nCard Last 4: {parsed_data.get('card_last_4', 'N/A')}")
    print(f"Statement Date: {parsed_data.get('statement_date', 'N/A')}")

    transactions = parsed_data.get('transactions', [])
    print(f"Transactions Found: {len(transactions)}")

    if transactions:
        print(f"\nFirst 5 Transactions:")
        print(f"{'Date':<12} {'Merchant':<40} {'Amount':>10}")
        print('-' * 65)

        for txn in transactions[:5]:
            date = str(txn.get('transaction_date', 'N/A'))
            merchant = str(txn.get('merchant_name', 'N/A'))[:40]
            amount = txn.get('amount', 0)
            refund = ' (Refund)' if txn.get('is_refund') else ''

            print(f"{date:<12} {merchant:<40} ${amount:>9.2f}{refund}")

        if len(transactions) > 5:
            print(f"\n... and {len(transactions) - 5} more transactions")

    return True


def main():
    """Run tests on all example statements"""
    statements_dir = Path("../statements")

    if not statements_dir.exists():
        print("❌ Statements directory not found!")
        return

    # Find all PDF files
    pdf_files = list(statements_dir.rglob("*.pdf"))

    if not pdf_files:
        print("❌ No PDF files found in statements directory!")
        return

    print(f"\nFound {len(pdf_files)} PDF file(s) to test")

    results = []
    for pdf_file in pdf_files:
        success = test_parser(pdf_file)
        results.append((pdf_file.name, success))

    # Summary
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print('='*80)

    passed = sum(1 for _, success in results if success)
    failed = len(results) - passed

    for filename, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {filename}")

    print(f"\nTotal: {len(results)} | Passed: {passed} | Failed: {failed}")

    if failed == 0:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n⚠️  {failed} test(s) failed")


if __name__ == "__main__":
    main()
