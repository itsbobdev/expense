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
from app.models import AssignmentRule, Person, Statement, Transaction


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


class FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.text = None
        self.reply_markup = None
        self.answered = False

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text, reply_markup=None):
        self.text = text
        self.reply_markup = reply_markup

    async def edit_message_reply_markup(self, reply_markup=None):
        self.reply_markup = reply_markup


def create_statement(db):
    statement = Statement(
        filename="alerts.json",
        bank_name="UOB",
        card_last_4="5750",
        statement_date=date(2025, 9, 2),
        billing_month="2025-09",
        raw_file_path="alerts.json",
    )
    db.add(statement)
    db.commit()
    return statement


def seed_card_owner(db, *, person_name: str, relationship_type: str, card_last_4: str):
    person = Person(
        name=person_name,
        relationship_type=relationship_type,
        card_last_4_digits=[card_last_4],
        is_auto_created=False,
    )
    db.add(person)
    db.flush()
    db.add(
        AssignmentRule(
            priority=100,
            rule_type="card_direct",
            conditions={"card_last_4": card_last_4},
            assign_to_person_id=person.id,
            is_active=True,
        )
    )
    db.commit()
    return person


@pytest.mark.asyncio
async def test_alerts_command_shows_card_fee_and_high_value_items(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        statement = create_statement(db)
        db.add_all(
            [
                Transaction(
                    statement_id=statement.id,
                    billing_month="2025-09",
                    transaction_date=date(2025, 8, 20),
                    merchant_name="ANNUAL FEE",
                    amount=240.0,
                    categories=["card_fees"],
                    alert_kind="card_fee",
                    alert_status="pending",
                ),
                Transaction(
                    statement_id=statement.id,
                    billing_month="2025-09",
                    transaction_date=date(2025, 8, 21),
                    merchant_name="BIG REFUND",
                    amount=-200.0,
                    is_refund=True,
                    categories=[],
                    alert_kind="high_value",
                    alert_status="unresolved",
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    message = FakeMessage()

    await handlers.alerts_command(SimpleNamespace(message=message), SimpleNamespace(user_data={}))

    texts = [call["text"] for call in message.calls]
    assert "Pending alerts: 2" in texts[0]
    assert any("[CARD FEE] [NEW] ANNUAL FEE" in text for text in texts[1:])
    assert any("[HIGH VALUE] [UNRESOLVED] BIG REFUND" in text for text in texts[1:])
    action_rows = [
        [button.text for button in call["reply_markup"].inline_keyboard[0]]
        for call in message.calls[1:]
    ]
    assert action_rows == [["Resolve"], ["Resolve"]]


@pytest.mark.asyncio
async def test_alerts_command_shows_card_owner_names_for_configured_cards(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        foo_wah_liang_stmt = Statement(
            filename="dad_alert.json",
            bank_name="UOB",
            card_last_4="4474",
            statement_date=date(2025, 12, 31),
            billing_month="2025-12",
            raw_file_path="dad_alert.json",
        )
        chan_zelin_stmt = Statement(
            filename="wife_alert.json",
            bank_name="Citibank",
            card_last_4="2065",
            statement_date=date(2025, 12, 31),
            billing_month="2025-12",
            raw_file_path="wife_alert.json",
        )
        db.add_all([foo_wah_liang_stmt, chan_zelin_stmt])
        db.commit()
        seed_card_owner(db, person_name="foo_wah_liang", relationship_type="parent", card_last_4="4474")
        seed_card_owner(db, person_name="chan_zelin", relationship_type="spouse", card_last_4="2065")
        db.add_all(
            [
                Transaction(
                    statement_id=foo_wah_liang_stmt.id,
                    billing_month="2025-12",
                    transaction_date=date(2025, 12, 3),
                    merchant_name="BIG FLIGHT BOOKING",
                    amount=333.0,
                    categories=["flights"],
                    alert_kind="high_value",
                    alert_status="pending",
                ),
                Transaction(
                    statement_id=chan_zelin_stmt.id,
                    billing_month="2025-12",
                    transaction_date=date(2025, 12, 4),
                    merchant_name="BIG HOTEL BOOKING",
                    amount=222.0,
                    categories=["travel_accommodation"],
                    alert_kind="high_value",
                    alert_status="pending",
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    message = FakeMessage()

    await handlers.alerts_command(SimpleNamespace(message=message), SimpleNamespace(user_data={}))

    texts = [call["text"] for call in message.calls[1:]]
    assert any("Card owner: foo_wah_liang" in text for text in texts)
    assert any("Card owner: chan_zelin" in text for text in texts)


@pytest.mark.asyncio
async def test_resolved_command_shows_kind_specific_details(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        statement = create_statement(db)
        reversal = Transaction(
            statement_id=statement.id,
            billing_month="2025-10",
            transaction_date=date(2025, 10, 5),
            merchant_name="ANNUAL FEE CREDIT ADJUSTMENT",
            amount=-240.0,
            is_refund=True,
            categories=["card_fees"],
            alert_kind="card_fee",
            alert_status="resolved",
            resolved_method="auto",
        )
        db.add(reversal)
        db.flush()
        db.add_all(
            [
                Transaction(
                    statement_id=statement.id,
                    billing_month="2025-09",
                    transaction_date=date(2025, 8, 20),
                    merchant_name="ANNUAL FEE",
                    amount=240.0,
                    categories=["card_fees"],
                    alert_kind="card_fee",
                    alert_status="resolved",
                    resolved_method="auto",
                    resolved_by_transaction_id=reversal.id,
                ),
                Transaction(
                    statement_id=statement.id,
                    billing_month="2025-09",
                    transaction_date=date(2025, 8, 21),
                    merchant_name="BIG HOTEL BOOKING",
                    amount=200.0,
                    categories=["travel_accommodation"],
                    alert_kind="high_value",
                    alert_status="resolved",
                    resolved_method="manual",
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    message = FakeMessage()

    await handlers.resolved_command(SimpleNamespace(message=message), SimpleNamespace(user_data={}))

    texts = [call["text"] for call in message.calls]
    assert "Resolved alerts (most recent 20):" in texts[0]
    assert any("[CARD FEE] [AUTO] ANNUAL FEE" in text and "Reversed by:" in text for text in texts[1:])
    assert any("[HIGH VALUE] [MANUAL] BIG HOTEL BOOKING" in text for text in texts[1:])
    action_rows = [
        [button.text for button in call["reply_markup"].inline_keyboard[0]]
        for call in message.calls[1:]
    ]
    assert len(action_rows) >= 2
    assert all(row == ["Mark Unresolved"] for row in action_rows)


@pytest.mark.asyncio
async def test_resolve_callback_swaps_to_resolved_message_with_undo(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        statement = create_statement(db)
        txn = Transaction(
            statement_id=statement.id,
            billing_month="2025-09",
            transaction_date=date(2025, 8, 21),
            merchant_name="BIG HOTEL BOOKING",
            amount=200.0,
            categories=["travel_accommodation"],
            alert_kind="high_value",
            alert_status="pending",
        )
        db.add(txn)
        db.commit()
        transaction_id = txn.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    query = FakeQuery(f"resolve_{transaction_id}")

    await handlers.handle_callback(SimpleNamespace(callback_query=query), SimpleNamespace(user_data={}))

    with session_local() as db:
        refreshed = db.query(Transaction).filter(Transaction.id == transaction_id).one()
        assert refreshed.alert_status == "resolved"
        assert refreshed.resolved_method == "manual"

    assert "[HIGH VALUE] [MANUAL] BIG HOTEL BOOKING" in query.text
    buttons = [button.text for button in query.reply_markup.inline_keyboard[0]]
    assert buttons == ["Mark Unresolved"]


@pytest.mark.asyncio
async def test_unresolve_callback_moves_alert_back_to_alerts_view(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        statement = create_statement(db)
        txn = Transaction(
            statement_id=statement.id,
            billing_month="2025-09",
            transaction_date=date(2025, 8, 21),
            merchant_name="BIG HOTEL BOOKING",
            amount=200.0,
            categories=["travel_accommodation"],
            alert_kind="high_value",
            alert_status="resolved",
            resolved_method="manual",
        )
        db.add(txn)
        db.commit()
        transaction_id = txn.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    query = FakeQuery(f"unresolve_{transaction_id}")

    await handlers.handle_callback(SimpleNamespace(callback_query=query), SimpleNamespace(user_data={}))

    with session_local() as db:
        refreshed = db.query(Transaction).filter(Transaction.id == transaction_id).one()
        assert refreshed.alert_status == "unresolved"
        assert refreshed.resolved_method is None

    assert "[HIGH VALUE] [UNRESOLVED] BIG HOTEL BOOKING" in query.text
    buttons = [button.text for button in query.reply_markup.inline_keyboard[0]]
    assert buttons == ["Resolve"]
