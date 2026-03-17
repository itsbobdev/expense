from sqlalchemy import Column, Integer, String, Boolean, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class BlacklistCategory(Base):
    __tablename__ = "blacklist_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    keywords = Column(JSON, nullable=False)  # List of keywords as JSON array
    is_active = Column(Boolean, default=True)

    # Relationships
    transactions = relationship("Transaction", back_populates="blacklist_category")

    def __repr__(self):
        return f"<BlacklistCategory(name='{self.name}', keywords={self.keywords})>"

    def matches(self, text: str) -> bool:
        """
        Check if any keyword matches the given text (case-insensitive, partial match).

        Args:
            text: The text to check against keywords (merchant name, description, etc.)

        Returns:
            True if any keyword is found in the text, False otherwise
        """
        if not self.is_active or not text:
            return False

        text_lower = text.lower()
        return any(keyword.lower() in text_lower for keyword in self.keywords)
