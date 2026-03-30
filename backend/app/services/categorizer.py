from typing import Optional, Set
from sqlalchemy.orm import Session
from app.models import Transaction, AssignmentRule, Person, BlacklistCategory
from dataclasses import dataclass


# All 9 categories that trigger manual review on self-card transactions.
# These are expenses that could be for family members (dad, wife).
REVIEW_TRIGGER_CATEGORIES: Set[str] = {
    "flights",
    "tours",
    "travel_accommodation",
    "accommodation",        # alias used in some extractions
    "subscriptions",
    "foreign_currency",
    "amaze",
    "atome",
    "paypal",
    "insurance",
    "town_council",
}


@dataclass
class AssignmentResult:
    """Result of transaction categorization"""
    person_id: Optional[int]
    person_name: Optional[str]
    confidence: float
    method: str
    needs_review: bool
    blacklist_category_id: Optional[int] = None
    matched_category: Optional[str] = None
    alert_status: Optional[str] = None


class TransactionCategorizer:
    """
    Categorizes transactions based on card-direct rules and category-triggered review.

    Flow:
    1. Check if card matches any card-direct rule (from YAML) → Direct assignment
    2. If no match, assign to "self" person
    3. For "self" assignments, check transaction's categories array against trigger list
    4. If any trigger category found → needs_review=True
    5. Otherwise → auto-assign to "self"
    """

    def __init__(self, db: Session):
        self.db = db
        self._category_id_cache: dict[str, int] = {}

    def categorize(self, transaction: Transaction) -> AssignmentResult:
        """
        Categorize a transaction using card-direct rules and category-triggered review.

        Args:
            transaction: Transaction to categorize

        Returns:
            AssignmentResult with person assignment and confidence
        """
        # Step 1: Try card-direct assignment (cards listed in YAML)
        card_result = self._try_card_direct_assignment(transaction)

        # Step 2: If no card match, assign to "self"
        if not card_result:
            self_person = self._get_or_create_self_person()
            card_result = AssignmentResult(
                person_id=self_person.id,
                person_name=self_person.name,
                confidence=1.0,
                method='self_auto',
                needs_review=False,
            )

        # Step 3: Check transaction categories against trigger list
        # Only for "self" person's cards — user books flights/tours for parents from own cards
        # Supplementary cardholders (parent, spouse) are always direct-billed
        is_self = self._is_self_person(card_result.person_id)
        matched_category = self._check_trigger_categories(transaction) if is_self else None

        if matched_category:
            category_id = self._get_blacklist_category_id(matched_category)
            return AssignmentResult(
                person_id=card_result.person_id,
                person_name=card_result.person_name,
                confidence=0.0,
                method='category_review',
                needs_review=True,
                blacklist_category_id=category_id,
                matched_category=matched_category,
            )

        # Step 4: Check for card_fees — set alert_status but don't trigger review
        card_result.alert_status = self._check_card_fee_alert(transaction)

        return card_result

    def _check_card_fee_alert(self, transaction: Transaction) -> Optional[str]:
        """
        If transaction has card_fees category and is not a refund, flag as pending alert.
        Refund card_fees get alert_status=None here; alert_resolver sets it later.
        """
        categories = getattr(transaction, 'categories', None) or []
        if 'card_fees' not in categories:
            return None
        if transaction.is_refund:
            return None  # alert_resolver will handle
        return 'pending'

    def _check_trigger_categories(self, transaction: Transaction) -> Optional[str]:
        """
        Check if any of the transaction's categories match the review trigger list.

        The categories array is set during PDF extraction and stored on the transaction.

        Returns:
            The first matching category name, or None
        """
        categories = getattr(transaction, 'categories', None) or []
        for cat in categories:
            if cat in REVIEW_TRIGGER_CATEGORIES:
                return cat
        return None

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
                needs_review=False,
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
                is_auto_created=True,
            )
            self.db.add(self_person)
            self.db.commit()
            self.db.refresh(self_person)

        return self_person

    def _is_self_person(self, person_id: Optional[int]) -> bool:
        """Check if the person is the 'self' user (foo_chi_jao)."""
        if not person_id:
            return False
        person = self.db.query(Person).filter(Person.id == person_id).first()
        return person is not None and person.relationship_type == "self"

    def _get_blacklist_category_id(self, category_name: str) -> Optional[int]:
        """Look up BlacklistCategory ID by name, with caching."""
        if category_name in self._category_id_cache:
            return self._category_id_cache[category_name]

        cat = (
            self.db.query(BlacklistCategory)
            .filter(BlacklistCategory.name == category_name)
            .first()
        )
        if cat:
            self._category_id_cache[category_name] = cat.id
            return cat.id
        return None
