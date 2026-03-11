import pdfplumber
from datetime import datetime
from typing import Dict, Any, List
from app.parsers.base import StatementParser
import re


class UOBParser(StatementParser):
    """Parser for UOB credit card statements"""

    def parse(self, file_path: str) -> Dict[str, Any]:
        """
        Parse UOB credit card statement PDF.

        UOB statements can contain multiple cards in one PDF,
        each with their own transactions.

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

                # Extract statement date (format: 02 MAR 2026)
                if not statement_date:
                    date_match = re.search(r'Statement Date\s+(\d{2}\s+[A-Z]{3}\s+\d{4})', text, re.IGNORECASE)
                    if date_match:
                        try:
                            statement_date = datetime.strptime(date_match.group(1), '%d %b %Y').date()
                        except ValueError:
                            pass

                # Extract first card number if not already found
                # Format: 4006-8220-4129-7857
                if not card_last_4:
                    card_match = re.search(r'(\d{4})-(\d{4})-(\d{4})-(\d{4})', text)
                    if card_match:
                        card_last_4 = card_match.group(4)

                # Parse transactions from text
                lines = text.split('\n')

                for i, line in enumerate(lines):
                    # UOB transaction pattern: POST_DATE TRANS_DATE DESCRIPTION AMOUNT
                    # Example: "09 FEB 07 FEB P@HDB* BILLRHAVRATA31B SINGAPORE 6.14"
                    # Example: "23 FEB 23 FEB PAYMT THRU E-BANK/HOMEB/CYBERB (EP23) 111.78 CR"

                    txn_match = re.match(
                        r'^(\d{2}\s+[A-Z]{3})\s+(\d{2}\s+[A-Z]{3})\s+(.+?)\s+([\d,]+\.\d{2})\s*(CR)?$',
                        line.strip()
                    )

                    if txn_match:
                        post_date_str = txn_match.group(1)
                        trans_date_str = txn_match.group(2)
                        merchant = txn_match.group(3).strip()
                        amount_str = txn_match.group(4).replace(',', '')
                        is_credit = txn_match.group(5) == 'CR'

                        # Skip non-transaction lines
                        skip_keywords = [
                            'PREVIOUS BALANCE',
                            'PAYMT THRU',
                            'SUB TOTAL',
                            'TOTAL BALANCE',
                            'PAYMENT'
                        ]
                        if any(kw in merchant.upper() for kw in skip_keywords):
                            continue

                        # Parse transaction date
                        try:
                            trans_date = self._parse_uob_date(trans_date_str, statement_date)
                            if not trans_date:
                                continue

                            amount = float(amount_str)
                            if is_credit:
                                amount = -amount

                            # Clean up merchant name (remove "Ref No." part)
                            merchant = re.sub(r'\s+Ref No\.\s*:.*$', '', merchant, flags=re.IGNORECASE)

                            transactions.append({
                                "transaction_date": trans_date,
                                "merchant_name": merchant.strip(),
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

    def _parse_uob_date(self, date_str: str, statement_date: Any) -> Any:
        """
        Parse UOB date format (e.g., '09 FEB') and infer year from statement date.

        Args:
            date_str: Date string in format DD MMM (e.g., '09 FEB')
            statement_date: Statement date to infer year

        Returns:
            date object or None
        """
        if not date_str or not statement_date:
            return None

        try:
            parts = date_str.strip().split()
            if len(parts) != 2:
                return None

            day = int(parts[0])
            month_str = parts[1]

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
        except (ValueError, AttributeError, IndexError):
            return None
