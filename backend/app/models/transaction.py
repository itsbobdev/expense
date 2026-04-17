from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("statements.id"), nullable=False)
    billing_month = Column(String, nullable=True, index=True)  # "2026-03" from folder path
    transaction_date = Column(Date, nullable=False)
    merchant_name = Column(String, nullable=False)
    raw_description = Column(String, nullable=True)   # original full description before cleaning
    amount = Column(Float, nullable=False)
    ccy_fee = Column(Float, nullable=True)             # CCY conversion fee merged from fee line
    transaction_type = Column(String, nullable=True)   # account statements: 'debit' | 'credit'
    is_refund = Column(Boolean, default=False)
    category = Column(String, nullable=True)
    categories = Column(JSON, nullable=True)           # categories array from JSON extraction
    country_code = Column(String(2), nullable=True)   # ISO 2-letter code e.g. "SG", "US"
    location = Column(String, nullable=True)           # city/region e.g. "SAN FRANCISCO"

    # Assignment fields
    assigned_to_person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    assignment_confidence = Column(Float, nullable=True)
    assignment_method = Column(String, nullable=True)  # card_direct, blacklist_review, self_auto, manual
    review_origin_method = Column(String, nullable=True)
    needs_review = Column(Boolean, default=False)
    reviewed_at = Column(DateTime, nullable=True)
    blacklist_category_id = Column(Integer, ForeignKey("blacklist_categories.id"), nullable=True)

    # Reward tracking
    is_reward = Column(Boolean, default=False)
    reward_type = Column(String, nullable=True)  # cashback | points | miles | uni_dollars

    # Refund tracking
    original_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)

    # Alert tracking
    alert_kind = Column(String, nullable=True, index=True)  # null, 'card_fee', 'high_value'
    alert_status = Column(String, nullable=True, index=True)  # null, 'pending', 'unresolved', 'resolved'
    parent_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)  # GST → parent fee
    resolved_by_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)  # fee → reversal
    resolved_method = Column(String, nullable=True)  # 'manual' or 'auto' (fee alerts only use 'auto')

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    statement = relationship("Statement", back_populates="transactions")
    assigned_person = relationship("Person", back_populates="transactions", foreign_keys=[assigned_to_person_id])
    original_transaction = relationship("Transaction", remote_side=[id], foreign_keys=[original_transaction_id])
    parent_transaction = relationship("Transaction", remote_side=[id], foreign_keys=[parent_transaction_id])
    resolved_by_transaction = relationship("Transaction", remote_side=[id], foreign_keys=[resolved_by_transaction_id])
    child_transactions = relationship("Transaction", foreign_keys="Transaction.parent_transaction_id")
    blacklist_category = relationship("BlacklistCategory", back_populates="transactions")
    ml_training_record = relationship("MLTrainingData", back_populates="transaction", uselist=False)
    bill_line_items = relationship("BillLineItem", back_populates="transaction")
    transaction_splits = relationship(
        "TransactionSplit",
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="TransactionSplit.sort_order",
    )
