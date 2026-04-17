from datetime import date
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.bot import handlers
from app.database import Base
from app.models import Statement, Transaction
from app.services.linked_refund_sync import ASSIGNMENT_METHOD_REFUND_LINKED_PENDING


def make_session_local():
    engine = create_engine("sqlite:///:memory:")
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    return session_local


class FakeMessage:
    def __init__(self):
        self.calls = []

    async def reply_text(self, text, reply_markup=None):
        self.calls.append({"text": text, "reply_markup": reply_markup})


@pytest.mark.asyncio
async def test_refunds_command_shows_linked_pending_refund_without_manual_actions(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        statement = Statement(
            filename="refunds.json",
            bank_name="UOB",
            card_last_4="5750",
            statement_date=date(2025, 9, 2),
            billing_month="2025-09",
            raw_file_path="refunds.json",
        )
        db.add(statement)
        db.flush()

        original = Transaction(
            statement_id=statement.id,
            billing_month="2025-09",
            transaction_date=date(2025, 8, 5),
            merchant_name="HILTON ADVPURCH8002367",
            amount=1957.53,
            needs_review=True,
            assignment_method="category_review",
        )
        db.add(original)
        db.flush()

        refund = Transaction(
            statement_id=statement.id,
            billing_month="2025-09",
            transaction_date=date(2025, 8, 14),
            merchant_name="HILTON ADVPURCH8002367",
            amount=-1957.53,
            is_refund=True,
            original_transaction_id=original.id,
            needs_review=True,
            assignment_method=ASSIGNMENT_METHOD_REFUND_LINKED_PENDING,
            review_origin_method="refund_auto_match",
        )
        db.add(refund)
        db.commit()

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    message = FakeMessage()

    await handlers.refunds_command(
        SimpleNamespace(message=message),
        SimpleNamespace(args=["2025-09"], user_data={}),
    )

    assert "Pending refunds for 2025-09: 1 transactions" in message.calls[0]["text"]
    detail = message.calls[1]
    assert "Linked refund 1/1:" in detail["text"]
    assert "Linked original still pending review:" in detail["text"]
    assert detail["reply_markup"] is None
