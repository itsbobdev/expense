from sqlalchemy import Column, Integer, String, Float, Date, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Statement(Base):
    __tablename__ = "statements"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    bank_name = Column(String, nullable=True)  # "Citibank", "Maybank", "UOB", "DBS"
    card_last_4 = Column(String(4), nullable=False)
    card_name = Column(String, nullable=True)  # e.g. "CITI REWARDS WORLD MASTERCARD"
    statement_date = Column(Date, nullable=False)
    billing_month = Column(String, nullable=True, index=True)  # "2026-03" from folder path
    period_start = Column(Date, nullable=True)  # inferred from earliest transaction date
    period_end = Column(Date, nullable=True)    # inferred from latest transaction date
    pdf_hash = Column(String(64), nullable=True, unique=True)  # SHA256 of source PDF for dedup
    total_charges = Column(Float, nullable=True)  # SUB-TOTAL from card section
    status = Column(String, default="pending")  # pending, processed, failed
    raw_file_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    # Relationships
    transactions = relationship("Transaction", back_populates="statement", cascade="all, delete-orphan")
    card_rewards = relationship("CardReward", back_populates="statement", cascade="all, delete-orphan")
