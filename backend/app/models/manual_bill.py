from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class ManualBill(Base):
    __tablename__ = "manual_bills"
    TYPE_RECURRING = "recurring"
    TYPE_MANUALLY_ADDED = "manually_added"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    billing_month = Column(String, nullable=False, index=True)  # Format: "2026-03"
    manual_type = Column(String, nullable=False, default=TYPE_RECURRING, server_default=TYPE_RECURRING)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    person = relationship("Person", back_populates="manual_bills")
    bill_line_items = relationship("BillLineItem", back_populates="manual_bill")

    def __repr__(self):
        return f"<ManualBill(person='{self.person.name if self.person else None}', amount={self.amount}, description='{self.description}')>"
