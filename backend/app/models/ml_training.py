from sqlalchemy import Column, Integer, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class MLTrainingData(Base):
    __tablename__ = "ml_training_data"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    features = Column(JSON, nullable=False)  # Extracted features for ML
    label = Column(Integer, ForeignKey("persons.id"), nullable=False)  # Person ID this was assigned to
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    transaction = relationship("Transaction", back_populates="ml_training_record")
    person = relationship("Person")
