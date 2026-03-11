from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models import Transaction, AssignmentRule, Person
from dataclasses import dataclass


@dataclass
class AssignmentResult:
    """Result of transaction categorization"""
    person_id: Optional[int]
    person_name: Optional[str]
    confidence: float
    method: str
    needs_review: bool


class TransactionCategorizer:
    """Categorizes transactions based on rules and ML predictions"""

    def __init__(self, db: Session):
        self.db = db

    def categorize(self, transaction: Transaction) -> AssignmentResult:
        """
        Categorize a transaction using rules in priority order.

        Args:
            transaction: Transaction to categorize

        Returns:
            AssignmentResult with person assignment and confidence
        """
        # Get all active rules ordered by priority (highest first)
        rules = (
            self.db.query(AssignmentRule)
            .filter(AssignmentRule.is_active == True)
            .order_by(AssignmentRule.priority.desc())
            .all()
        )

        # Try each rule in order
        for rule in rules:
            if self._matches_rule(transaction, rule):
                person = self.db.query(Person).filter(Person.id == rule.assign_to_person_id).first()
                return AssignmentResult(
                    person_id=person.id,
                    person_name=person.name,
                    confidence=1.0,
                    method=rule.rule_type,
                    needs_review=False,
                )

        # No rule matched - needs review
        return AssignmentResult(
            person_id=None,
            person_name=None,
            confidence=0.0,
            method="none",
            needs_review=True,
        )

    def _matches_rule(self, transaction: Transaction, rule: AssignmentRule) -> bool:
        """
        Check if a transaction matches a rule's conditions.

        Args:
            transaction: Transaction to check
            rule: Rule to match against

        Returns:
            True if the transaction matches all conditions
        """
        conditions = rule.conditions

        # Card direct matching
        if rule.rule_type == "card_direct":
            card_last_4 = conditions.get("card_last_4")
            if card_last_4:
                # Get card from statement
                if transaction.statement and transaction.statement.card_last_4 == card_last_4:
                    return True

        # Category matching
        elif rule.rule_type == "category":
            required_card = conditions.get("card_last_4")
            required_categories = conditions.get("category", [])

            # Check card match if specified
            if required_card:
                if not transaction.statement or transaction.statement.card_last_4 != required_card:
                    return False

            # Check category match
            if required_categories:
                # Detect category from merchant name
                detected_category = self._detect_category(transaction.merchant_name)
                if detected_category in required_categories:
                    return True

        # Merchant matching
        elif rule.rule_type == "merchant":
            merchant_keywords = conditions.get("merchant_keywords", [])
            merchant_lower = transaction.merchant_name.lower()

            for keyword in merchant_keywords:
                if keyword.lower() in merchant_lower:
                    return True

        return False

    def _detect_category(self, merchant_name: str) -> Optional[str]:
        """
        Detect transaction category from merchant name.

        Args:
            merchant_name: Name of the merchant

        Returns:
            Category string or None
        """
        merchant_lower = merchant_name.lower()

        # Transport categories (for Scenario 2)
        bus_keywords = ['sbs', 'smrt bus', 'tower transit', 'go-ahead']
        if any(kw in merchant_lower for kw in bus_keywords):
            return 'transport_bus'

        mrt_keywords = ['mrt', 'simplygo', 'ez-link', 'ez link']
        if any(kw in merchant_lower for kw in mrt_keywords):
            return 'transport_mrt'

        # Parent categories (for Scenario 3 - keyword heuristics)
        flight_keywords = ['jetstar', 'scoot', 'changi', 'airline', 'airways', 'singapore air']
        if any(kw in merchant_lower for kw in flight_keywords):
            return 'parent_flight'

        tour_keywords = ['tour', 'klook', 'pelago', 'chan brothers', 'travel agency']
        if any(kw in merchant_lower for kw in tour_keywords):
            return 'parent_tour'

        cleaning_keywords = ['helper', 'maid', 'cleaning service']
        if any(kw in merchant_lower for kw in cleaning_keywords):
            return 'parent_cleaning'

        return None
