"""
Blacklist Matcher Service

Handles keyword-based matching for blacklist categories to determine
if transactions should trigger manual review.
"""
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models import BlacklistCategory


class BlacklistMatcher:
    """Service for matching transactions against blacklist categories."""

    def __init__(self, db: Session):
        self.db = db
        self._categories: Optional[List[BlacklistCategory]] = None

    def _load_categories(self) -> List[BlacklistCategory]:
        """Load all active blacklist categories from database."""
        if self._categories is None:
            self._categories = (
                self.db.query(BlacklistCategory)
                .filter(BlacklistCategory.is_active == True)
                .all()
            )
        return self._categories

    def check_blacklist(
        self,
        merchant_name: str,
        description: str = "",
        location: str = ""
    ) -> Optional[BlacklistCategory]:
        """
        Check if transaction matches any blacklist category.

        Args:
            merchant_name: The merchant name from the transaction
            description: Additional transaction description (optional)
            location: Transaction location (optional)

        Returns:
            The BlacklistCategory object if a match is found, None otherwise
        """
        # Combine all text fields for comprehensive matching
        combined_text = f"{merchant_name} {description} {location}".lower()

        # Check against all active categories
        categories = self._load_categories()

        for category in categories:
            if category.matches(combined_text):
                return category

        return None

    def add_category(
        self,
        name: str,
        keywords: List[str],
        is_active: bool = True
    ) -> BlacklistCategory:
        """
        Add a new blacklist category.

        Args:
            name: Category name (e.g., "flights", "tours")
            keywords: List of keywords to match
            is_active: Whether the category is active (default: True)

        Returns:
            The created BlacklistCategory object
        """
        category = BlacklistCategory(
            name=name,
            keywords=keywords,
            is_active=is_active
        )
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)

        # Invalidate cache
        self._categories = None

        return category

    def add_keywords_to_category(
        self,
        category_name: str,
        keywords: List[str]
    ) -> BlacklistCategory:
        """
        Add keywords to an existing category.

        Args:
            category_name: Name of the category to update
            keywords: List of keywords to add

        Returns:
            The updated BlacklistCategory object

        Raises:
            ValueError: If category not found
        """
        category = (
            self.db.query(BlacklistCategory)
            .filter(BlacklistCategory.name == category_name)
            .first()
        )

        if not category:
            raise ValueError(f"Category '{category_name}' not found")

        # Merge new keywords with existing ones (avoid duplicates)
        existing_keywords = set(k.lower() for k in category.keywords)
        new_keywords = [k for k in keywords if k.lower() not in existing_keywords]

        if new_keywords:
            category.keywords = category.keywords + new_keywords
            self.db.commit()
            self.db.refresh(category)

            # Invalidate cache
            self._categories = None

        return category

    def get_all_categories(self) -> List[BlacklistCategory]:
        """Get all blacklist categories (active and inactive)."""
        return self.db.query(BlacklistCategory).all()

    def deactivate_category(self, category_name: str) -> BlacklistCategory:
        """
        Deactivate a blacklist category.

        Args:
            category_name: Name of the category to deactivate

        Returns:
            The updated BlacklistCategory object

        Raises:
            ValueError: If category not found
        """
        category = (
            self.db.query(BlacklistCategory)
            .filter(BlacklistCategory.name == category_name)
            .first()
        )

        if not category:
            raise ValueError(f"Category '{category_name}' not found")

        category.is_active = False
        self.db.commit()
        self.db.refresh(category)

        # Invalidate cache
        self._categories = None

        return category
