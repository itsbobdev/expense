from sqlalchemy import Column, Integer, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class TransactionSplit(Base):
    __tablename__ = "transaction_splits"
    __table_args__ = (
        UniqueConstraint("transaction_id", "person_id", name="uq_transaction_splits_transaction_person"),
    )

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=False, index=True)
    split_amount = Column(Float, nullable=False)
    split_percent = Column(Float, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)

    transaction = relationship("Transaction", back_populates="transaction_splits")
    person = relationship("Person", back_populates="transaction_splits")
