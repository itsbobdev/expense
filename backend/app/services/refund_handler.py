"""
Refund Handler Service

Handles automatic matching of refund transactions to their original transactions.
"""
from typing import Optional, List
from datetime import timedelta
from sqlalchemy.orm import Session
from app.models import Transaction


class RefundHandler:
    """Service for matching refund transactions to original transactions."""

    def __init__(self, db: Session):
        self.db = db

    def process_refund(self, refund_transaction: Transaction) -> bool:
        """
        Process a refund transaction and try to match it to an original transaction.

        Args:
            refund_transaction: The refund transaction (negative amount)

        Returns:
            True if auto-matched successfully, False if needs manual review
        """
        # Step 1: Identify refund (negative amount)
        if refund_transaction.amount >= 0:
            # Not a refund
            return False

        # Step 2: Find potential original transactions
        original_amount = -refund_transaction.amount  # Convert to positive

        # Search for original transaction within 90 days before the refund
        earliest_date = refund_transaction.transaction_date - timedelta(days=90)

        candidates = (
            self.db.query(Transaction)
            .filter(
                Transaction.merchant_name == refund_transaction.merchant_name,
                Transaction.amount == original_amount,  # Exact amount match
                Transaction.transaction_date < refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest_date,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id  # Not the same transaction
            )
            .all()
        )

        if len(candidates) == 1:
            # Exact match found → auto-assign
            original = candidates[0]

            # Assign refund to same person as original
            refund_transaction.assigned_to_person_id = original.assigned_to_person_id
            refund_transaction.original_transaction_id = original.id
            refund_transaction.is_refund = True
            refund_transaction.assignment_confidence = 0.95
            refund_transaction.assignment_method = 'refund_auto_match'
            refund_transaction.needs_review = False

            self.db.commit()

            return True

        elif len(candidates) > 1:
            # Multiple matches → needs review
            refund_transaction.is_refund = True
            refund_transaction.needs_review = True
            refund_transaction.assignment_method = 'refund_ambiguous'

            self.db.commit()

            return False

        else:
            # No match found → needs review
            refund_transaction.is_refund = True
            refund_transaction.needs_review = True
            refund_transaction.assignment_method = 'refund_orphan'

            self.db.commit()

            return False

    def get_refund_candidates(
        self,
        refund_transaction: Transaction
    ) -> List[Transaction]:
        """
        Get potential original transactions for a refund.

        Args:
            refund_transaction: The refund transaction

        Returns:
            List of candidate original transactions
        """
        if refund_transaction.amount >= 0:
            return []

        original_amount = -refund_transaction.amount
        earliest_date = refund_transaction.transaction_date - timedelta(days=90)

        candidates = (
            self.db.query(Transaction)
            .filter(
                Transaction.merchant_name == refund_transaction.merchant_name,
                Transaction.amount == original_amount,
                Transaction.transaction_date < refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest_date,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id
            )
            .order_by(Transaction.transaction_date.desc())
            .all()
        )

        return candidates

    def match_refund_manually(
        self,
        refund_transaction_id: int,
        original_transaction_id: int
    ) -> Transaction:
        """
        Manually match a refund to an original transaction.

        Args:
            refund_transaction_id: ID of the refund transaction
            original_transaction_id: ID of the original transaction

        Returns:
            The updated refund transaction

        Raises:
            ValueError: If transactions not found or invalid
        """
        refund = self.db.query(Transaction).filter(Transaction.id == refund_transaction_id).first()
        original = self.db.query(Transaction).filter(Transaction.id == original_transaction_id).first()

        if not refund or not original:
            raise ValueError("Transaction not found")

        if refund.amount >= 0:
            raise ValueError("Not a refund transaction (amount must be negative)")

        # Match the refund
        refund.assigned_to_person_id = original.assigned_to_person_id
        refund.original_transaction_id = original.id
        refund.is_refund = True
        refund.assignment_confidence = 1.0
        refund.assignment_method = 'refund_manual_match'
        refund.needs_review = False

        self.db.commit()
        self.db.refresh(refund)

        return refund
