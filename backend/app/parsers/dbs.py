import pdfplumber
from datetime import datetime
from typing import Dict, Any, List
from app.parsers.base import StatementParser
import re


class DBSParser(StatementParser):
    """Parser for DBS/POSB credit card statements"""

    def parse(self, file_path: str) -> Dict[str, Any]:
        """
        Parse DBS/POSB credit card statement PDF.

        Args:
            file_path: Path to the PDF file

        Returns:
            Dictionary containing card info and transactions
        """
        transactions = []
        card_last_4 = None
        statement_date = None

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()

                # Extract card number (look for pattern like "Card ending in 1234")
                if not card_last_4:
                    card_match = re.search(r'(?:Card|ending in|xxxx)\s*(\d{4})', text, re.IGNORECASE)
                    if card_match:
                        card_last_4 = card_match.group(1)

                # Extract statement date
                if not statement_date:
                    date_match = re.search(r'Statement Date[:\s]+(\d{1,2}\s+\w+\s+\d{4})', text, re.IGNORECASE)
                    if date_match:
                        try:
                            statement_date = datetime.strptime(date_match.group(1), '%d %b %Y').date()
                        except ValueError:
                            pass

                # Extract table data
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue

                    # Find header row to identify column indices
                    header_row = None
                    for i, row in enumerate(table):
                        if row and any(cell and 'date' in str(cell).lower() for cell in row):
                            header_row = i
                            break

                    if header_row is None:
                        continue

                    # Process transaction rows
                    for row in table[header_row + 1:]:
                        if not row or len(row) < 3:
                            continue

                        try:
                            # Typical DBS format: Date | Description | Amount
                            date_str = str(row[0]).strip() if row[0] else None
                            merchant = str(row[1]).strip() if row[1] else None
                            amount_str = str(row[-1]).strip() if row[-1] else None

                            if not date_str or not merchant or not amount_str:
                                continue

                            # Parse date
                            transaction_date = self._parse_date(date_str)
                            if not transaction_date:
                                continue

                            # Parse amount (handle negative amounts and currency symbols)
                            amount = self._parse_amount(amount_str)
                            if amount is None:
                                continue

                            # Skip header-like rows
                            if 'total' in merchant.lower() or 'balance' in merchant.lower():
                                continue

                            transactions.append({
                                "transaction_date": transaction_date,
                                "merchant_name": merchant,
                                "amount": amount,
                                "is_refund": self.detect_refund(amount, merchant),
                            })

                        except (ValueError, IndexError) as e:
                            # Skip rows that can't be parsed
                            continue

        return {
            "card_last_4": card_last_4,
            "statement_date": statement_date,
            "transactions": transactions,
        }

    def _parse_date(self, date_str: str) -> Any:
        """Parse date from various formats"""
        if not date_str or date_str == 'None':
            return None

        # Try different date formats
        formats = [
            '%d/%m/%Y',
            '%d-%m-%Y',
            '%d %b %Y',
            '%d %B %Y',
            '%d/%m/%y',
            '%d-%m-%y',
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        return None

    def _parse_amount(self, amount_str: str) -> float:
        """Parse amount from string, handling currency symbols and negatives"""
        if not amount_str or amount_str == 'None':
            return None

        # Remove currency symbols and spaces
        amount_str = re.sub(r'[S$\s,]', '', amount_str)

        # Handle parentheses as negative (accounting format)
        if amount_str.startswith('(') and amount_str.endswith(')'):
            amount_str = '-' + amount_str[1:-1]

        try:
            return float(amount_str)
        except ValueError:
            return None
