"""
Refund Handler Service

Handles automatic matching of refund transactions to their original transactions.
"""
from typing import Optional, List
from datetime import timedelta
from sqlalchemy.orm import Session
from app.models import Transaction
from app.models.statement import Statement


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
        earliest_date = refund_transaction.transaction_date - timedelta(days=180)

        candidates = (
            self.db.query(Transaction)
            .filter(
                Transaction.merchant_name == refund_transaction.merchant_name,
                Transaction.amount == original_amount,  # Exact amount match
                Transaction.transaction_date <= refund_transaction.transaction_date,
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
        earliest_date = refund_transaction.transaction_date - timedelta(days=180)

        candidates = (
            self.db.query(Transaction)
            .filter(
                Transaction.merchant_name == refund_transaction.merchant_name,
                Transaction.amount == original_amount,
                Transaction.transaction_date <= refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest_date,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id
            )
            .order_by(Transaction.transaction_date.desc())
            .all()
        )

        return candidates

    def get_broad_candidates(self, refund_transaction: Transaction) -> List[Transaction]:
        """
        Broader tiered search for refund matching when exact match fails.

        Tier 1: Exact merchant + exact amount (existing behavior)
        Tier 2: Same card + exact amount + 180-day window
        Tier 3: Same card + similar amount (within 10%) + 180-day window
        Tier 4: Same card + merchant name substring match + 180-day window
        """
        abs_amount = abs(refund_transaction.amount)
        earliest = refund_transaction.transaction_date - timedelta(days=180)
        card_last_4 = refund_transaction.statement.card_last_4 if refund_transaction.statement else None

        # Tier 1: exact merchant + exact amount (existing)
        tier1 = self.get_refund_candidates(refund_transaction)
        if tier1:
            return tier1

        if not card_last_4:
            return []

        # Tier 2: same card + exact amount
        tier2 = (
            self.db.query(Transaction)
            .join(Statement)
            .filter(
                Statement.card_last_4 == card_last_4,
                Transaction.amount == abs_amount,
                Transaction.transaction_date <= refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id,
            )
            .order_by(Transaction.transaction_date.desc())
            .all()
        )
        if tier2:
            return tier2

        # Tier 3: same card + similar amount (within 10%)
        lower = abs_amount * 0.9
        upper = abs_amount * 1.1
        tier3 = (
            self.db.query(Transaction)
            .join(Statement)
            .filter(
                Statement.card_last_4 == card_last_4,
                Transaction.amount.between(lower, upper),
                Transaction.transaction_date <= refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id,
            )
            .order_by(Transaction.transaction_date.desc())
            .all()
        )
        if tier3:
            return tier3

        # Tier 4: same card + merchant name substring match
        refund_merchant = refund_transaction.merchant_name.upper()
        same_card_txns = (
            self.db.query(Transaction)
            .join(Statement)
            .filter(
                Statement.card_last_4 == card_last_4,
                Transaction.transaction_date <= refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id,
            )
            .order_by(Transaction.transaction_date.desc())
            .all()
        )
        tier4 = [
            t for t in same_card_txns
            if t.merchant_name and (
                t.merchant_name.upper() in refund_merchant
                or refund_merchant in t.merchant_name.upper()
            )
        ]
        if tier4:
            return tier4

        return []

    def search_by_amount(self, refund_transaction: Transaction, limit: int = 10) -> List[Transaction]:
        """Search all non-refund transactions matching the absolute refund amount."""
        abs_amount = abs(refund_transaction.amount)
        return (
            self.db.query(Transaction)
            .filter(
                Transaction.amount == abs_amount,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id,
            )
            .order_by(Transaction.transaction_date.desc())
            .limit(limit)
            .all()
        )

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
