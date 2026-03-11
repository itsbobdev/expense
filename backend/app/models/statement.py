from sqlalchemy import Column, Integer, String, Date, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Statement(Base):
    __tablename__ = "statements"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    card_last_4 = Column(String(4), nullable=False)
    statement_date = Column(Date, nullable=False)
    status = Column(String, default="pending")  # pending, processed, failed
    raw_file_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    # Relationships
    transactions = relationship("Transaction", back_populates="statement", cascade="all, delete-orphan")
