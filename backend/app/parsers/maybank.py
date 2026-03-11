import pdfplumber
from datetime import datetime
from typing import Dict, Any, List
from app.parsers.base import StatementParser
import re


class MaybankParser(StatementParser):
    """Parser for Maybank credit card statements"""

    def parse(self, file_path: str) -> Dict[str, Any]:
        """
        Parse Maybank credit card statement PDF.

        Maybank statements group transactions by cardholder name
        under the same card number family.

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

                # Extract card number (format: 5547-0402-2384-0005)
                if not card_last_4:
                    card_match = re.search(r'(\d{4})-(\d{4})-(\d{4})-(\d{4})', text)
                    if card_match:
                        card_last_4 = card_match.group(4)

                # Extract statement date (format: 25/01/2026)
                if not statement_date:
                    date_match = re.search(r'STATEMENT DATE\s+(\d{2}/\d{2}/\d{4})', text, re.IGNORECASE)
                    if date_match:
                        try:
                            statement_date = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
                        except ValueError:
                            pass

                # Parse transactions from text (Maybank uses specific format)
                lines = text.split('\n')

                for i, line in enumerate(lines):
                    # Look for transaction pattern: DATE DATE DESCRIPTION AMOUNT
                    # Example: "07JAN 09JAN SERAYA ENERGY PTE LTD SINGAPORE 40.74"
                    txn_match = re.match(
                        r'^(\d{2}[A-Z]{3})\s+(\d{2}[A-Z]{3})\s+(.+?)\s+([\d,]+\.\d{2})(CR)?$',
                        line.strip()
                    )

                    if txn_match:
                        trans_date_str = txn_match.group(1)
                        post_date_str = txn_match.group(2)
                        merchant = txn_match.group(3).strip()
                        amount_str = txn_match.group(4).replace(',', '')
                        is_credit = txn_match.group(5) == 'CR'

                        # Skip non-transaction lines
                        skip_keywords = [
                            'OUTSTANDING BALANCE',
                            'PAYMENT',
                            'TOTAL TRANSACTIONS',
                            'PAYMENT RECEIVED',
                            'ANNUAL FEE',
                            'GST @'
                        ]
                        if any(kw in merchant.upper() for kw in skip_keywords):
                            continue

                        # Parse transaction date (need to infer year from statement date)
                        try:
                            trans_date = self._parse_maybank_date(trans_date_str, statement_date)
                            if not trans_date:
                                continue

                            amount = float(amount_str)
                            if is_credit:
                                amount = -amount

                            transactions.append({
                                "transaction_date": trans_date,
                                "merchant_name": merchant,
                                "amount": amount,
                                "is_refund": self.detect_refund(amount, merchant),
                            })
                        except (ValueError, AttributeError):
                            continue

        return {
            "card_last_4": card_last_4,
            "statement_date": statement_date,
            "transactions": transactions,
        }

    def _parse_maybank_date(self, date_str: str, statement_date: Any) -> Any:
        """
        Parse Maybank date format (e.g., '07JAN') and infer year from statement date.

        Args:
            date_str: Date string in format DDMMM (e.g., '07JAN')
            statement_date: Statement date to infer year

        Returns:
            date object or None
        """
        if not date_str or not statement_date:
            return None

        try:
            # Parse day and month
            day = int(date_str[:2])
            month_str = date_str[2:]

            # Convert month abbreviation to number
            month_map = {
                'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4,
                'MAY': 5, 'JUN': 6, 'JUL': 7, 'AUG': 8,
                'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
            }

            month = month_map.get(month_str.upper())
            if not month:
                return None

            # Infer year: if transaction month is after statement month,
            # it's from the previous year
            year = statement_date.year
            if month > statement_date.month:
                year -= 1

            return datetime(year, month, day).date()
        except (ValueError, AttributeError):
            return None
