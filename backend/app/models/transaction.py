from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("statements.id"), nullable=False)
    transaction_date = Column(Date, nullable=False)
    merchant_name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    is_refund = Column(Boolean, default=False)
    category = Column(String, nullable=True)

    # Assignment fields
    assigned_to_person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    assignment_confidence = Column(Float, nullable=True)
    assignment_method = Column(String, nullable=True)  # card_direct, keyword_heuristic, ml_auto, ml_suggest, manual
    needs_review = Column(Boolean, default=False)
    reviewed_at = Column(DateTime, nullable=True)

    # Refund tracking
    original_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    statement = relationship("Statement", back_populates="transactions")
    assigned_person = relationship("Person", back_populates="transactions", foreign_keys=[assigned_to_person_id])
    original_transaction = relationship("Transaction", remote_side=[id], foreign_keys=[original_transaction_id])
    ml_training_record = relationship("MLTrainingData", back_populates="transaction", uselist=False)
    bill_line_items = relationship("BillLineItem", back_populates="transaction")
