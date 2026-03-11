from abc import ABC, abstractmethod
from typing import List, Dict, Any
from datetime import date


class StatementParser(ABC):
    """Base class for credit card statement parsers"""

    @abstractmethod
    def parse(self, file_path: str) -> Dict[str, Any]:
        """
        Parse a credit card statement PDF and extract transaction data.

        Args:
            file_path: Path to the PDF file

        Returns:
            Dictionary containing:
                - card_last_4: Last 4 digits of the card
                - statement_date: Date of the statement
                - transactions: List of transaction dictionaries
        """
        pass

    def _parse_transaction(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a single transaction row into a standardized format.

        Args:
            row: Raw transaction data

        Returns:
            Dictionary with keys: transaction_date, merchant_name, amount
        """
        return {
            "transaction_date": row.get("date"),
            "merchant_name": row.get("merchant"),
            "amount": row.get("amount"),
        }

    def detect_refund(self, amount: float, merchant_name: str) -> bool:
        """
        Detect if a transaction is a refund based on amount and merchant name.

        Args:
            amount: Transaction amount
            merchant_name: Merchant name

        Returns:
            True if the transaction is likely a refund
        """
        # Negative amounts are typically refunds
        if amount < 0:
            return True

        # Some merchants explicitly mark refunds
        refund_keywords = ["refund", "reversal", "credit"]
        if any(kw in merchant_name.lower() for kw in refund_keywords):
            return True

        return False
