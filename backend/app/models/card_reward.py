from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class CardReward(Base):
    __tablename__ = "card_rewards"

    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("statements.id"), nullable=True)
    billing_month = Column(String, nullable=False, index=True)  # "YYYY-MM"
    card_last_4 = Column(String(4), nullable=True)
    bank_name = Column(String, nullable=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    reward_type = Column(String, nullable=False)  # cashback | points | miles | uni_dollars
    earned_this_period = Column(Float, nullable=False)  # SGD for cashback; count for points/miles
    balance = Column(Float, nullable=True)            # running balance if shown in statement
    expiry_date = Column(Date, nullable=True)         # from statement, if shown
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    statement = relationship("Statement", back_populates="card_rewards")
    person = relationship("Person", back_populates="card_rewards")
