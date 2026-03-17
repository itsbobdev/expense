from sqlalchemy import Column, Integer, String, JSON, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


class Person(Base):
    __tablename__ = "persons"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    relationship_type = Column(String, nullable=False)  # 'parent', 'spouse', 'self'
    card_last_4_digits = Column(JSON, default=list)  # List of card numbers
    is_auto_created = Column(Boolean, default=False)  # True for auto-created "self" person

    # Relationships
    transactions = relationship("Transaction", back_populates="assigned_person")
    bills = relationship("Bill", back_populates="person")
    assignment_rules = relationship("AssignmentRule", back_populates="person")
    manual_bills = relationship("ManualBill", back_populates="person")
