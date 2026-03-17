from typing import Optional
from sqlalchemy.orm import Session
from app.models import Transaction, AssignmentRule, Person, BlacklistCategory
from app.services.blacklist_matcher import BlacklistMatcher
from dataclasses import dataclass


@dataclass
class AssignmentResult:
    """Result of transaction categorization"""
    person_id: Optional[int]
    person_name: Optional[str]
    confidence: float
    method: str
    needs_review: bool
    blacklist_category_id: Optional[int] = None


class TransactionCategorizer:
    """
    Categorizes transactions based on card-direct rules and blacklist matching.

    Flow:
    1. Check if card matches any card-direct rule (from YAML) → Direct assignment
    2. If no match, assign to "self" person
    3. For "self" assignments, check against blacklist categories
    4. If blacklist match → needs_review=True
    5. Otherwise → auto-assign to "self"
    """

    def __init__(self, db: Session):
        self.db = db
        self.blacklist_matcher = BlacklistMatcher(db)

    def categorize(self, transaction: Transaction) -> AssignmentResult:
        """
        Categorize a transaction using card-direct rules and blacklist checking.

        Args:
            transaction: Transaction to categorize

        Returns:
            AssignmentResult with person assignment and confidence
        """
        # Step 1: Try card-direct assignment (cards listed in YAML)
        card_result = self._try_card_direct_assignment(transaction)
        if card_result:
            return card_result

        # Step 2: Card not in YAML → belongs to "self"
        self_person = self._get_or_create_self_person()

        # Step 3: Check blacklist for "self" transactions
        blacklist_category = self.blacklist_matcher.check_blacklist(
            merchant_name=transaction.merchant_name,
            description=getattr(transaction, 'description', ''),
            location=getattr(transaction, 'location', '')
        )

        if blacklist_category:
            # Trigger manual review
            return AssignmentResult(
                person_id=self_person.id,
                person_name=self_person.name,
                confidence=0.0,
                method='blacklist_review',
                needs_review=True,
                blacklist_category_id=blacklist_category.id
            )
        else:
            # Auto-assign to self
            return AssignmentResult(
                person_id=self_person.id,
                person_name=self_person.name,
                confidence=1.0,
                method='self_auto',
                needs_review=False
            )

    def _try_card_direct_assignment(self, transaction: Transaction) -> Optional[AssignmentResult]:
        """
        Try to assign transaction based on card-direct rules.

        Args:
            transaction: Transaction to check

        Returns:
            AssignmentResult if card matches, None otherwise
        """
        if not transaction.statement:
            return None

        card_last_4 = transaction.statement.card_last_4

        # Get card-direct rules for this card
        rule = (
            self.db.query(AssignmentRule)
            .filter(
                AssignmentRule.is_active == True,
                AssignmentRule.rule_type == "card_direct"
            )
            .filter(AssignmentRule.conditions.contains({"card_last_4": card_last_4}))
            .first()
        )

        if rule:
            person = self.db.query(Person).filter(Person.id == rule.assign_to_person_id).first()
            return AssignmentResult(
                person_id=person.id,
                person_name=person.name,
                confidence=1.0,
                method='card_direct',
                needs_review=False
            )

        return None

    def _get_or_create_self_person(self) -> Person:
        """
        Get or create the "self" person for transactions not matching YAML cards.

        Returns:
            Person object for "self"
        """
        self_person = (
            self.db.query(Person)
            .filter(Person.relationship_type == "self")
            .first()
        )

        if not self_person:
            self_person = Person(
                name="Self",
                relationship_type="self",
                card_last_4_digits=[],
                is_auto_created=True
            )
            self.db.add(self_person)
            self.db.commit()
            self.db.refresh(self_person)

        return self_person
