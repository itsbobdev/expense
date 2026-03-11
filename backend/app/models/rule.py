from sqlalchemy import Column, Integer, String, JSON, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


class AssignmentRule(Base):
    __tablename__ = "assignment_rules"

    id = Column(Integer, primary_key=True, index=True)
    priority = Column(Integer, nullable=False, default=50)  # Higher priority = evaluated first
    rule_type = Column(String, nullable=False)  # card_direct, category, merchant
    conditions = Column(JSON, nullable=False)  # JSON object with conditions
    assign_to_person_id = Column(Integer, ForeignKey("persons.id"), nullable=False)
    is_active = Column(Boolean, default=True)

    # Relationships
    person = relationship("Person", back_populates="assignment_rules")
