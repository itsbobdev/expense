from datetime import date
from types import SimpleNamespace
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.bot import handlers
from app.database import Base
from app.models import AssignmentRule, Bill, BillLineItem, Person, Statement, Transaction
from app.services.bill_generator import BillGenerator
from app.services.review_assignment import (
    assign_transaction_equal_split,
    assign_transaction_to_person,
    undo_review_assignment,
)


def make_session_local():
    engine = create_engine("sqlite:///:memory:")
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    return session_local


def create_people(db):
    dad = Person(name="Dad", relationship_type="parent", card_last_4_digits=["1234"], is_auto_created=False)
    wife = Person(name="Wife", relationship_type="spouse", card_last_4_digits=["5678"], is_auto_created=False)
    self_person = Person(name="Self", relationship_type="self", card_last_4_digits=[], is_auto_created=True)
    db.add_all([dad, wife, self_person])
    db.commit()
    return dad, wife, self_person


def create_statement(db, billing_month: str = "2026-03"):
    statement = Statement(
        filename=f"{billing_month}.json",
        bank_name="UOB",
        card_last_4="1234",
        statement_date=date(2026, 3, 31),
        billing_month=billing_month,
        raw_file_path=f"{billing_month}.json",
    )
    db.add(statement)
    db.commit()
    return statement


def create_card_direct_rule(db, person: Person, card_last_4: str):
    rule = AssignmentRule(
        priority=100,
        rule_type="card_direct",
        conditions={"card_last_4": card_last_4},
        assign_to_person_id=person.id,
        is_active=True,
    )
    db.add(rule)
    db.commit()
    return rule


def create_transaction(
    db,
    statement: Statement,
    merchant_name: str,
    amount: float,
    *,
    billing_month: str = "2026-03",
    needs_review: bool = True,
    assignment_method: str = "category_review",
    review_origin_method: str | None = "category_review",
    assigned_to_person_id: int | None = None,
) -> Transaction:
    txn = Transaction(
        statement_id=statement.id,
        billing_month=billing_month,
        transaction_date=date(2026, 3, 15),
        merchant_name=merchant_name,
        amount=amount,
        assigned_to_person_id=assigned_to_person_id,
        assignment_method=assignment_method,
        review_origin_method=review_origin_method,
        needs_review=needs_review,
        categories=["travel"],
    )
    db.add(txn)
    db.commit()
    return txn


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


def make_callback(data: str):
    query = FakeQuery(data)
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(user_data={})
    return update, context, query


@pytest.mark.asyncio
async def test_direct_assignment_callback_adds_undo_button(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        statement = create_statement(db)
        txn = create_transaction(db, statement, "DIRECT ASSIGNMENT", 42.0)
        transaction_id = txn.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    update, context, query = make_callback(f"assign_{transaction_id}_{dad.id}")

    await handlers.handle_callback(update, context)

    with session_local() as db:
        txn = db.query(Transaction).filter(Transaction.id == transaction_id).one()
        assert txn.assigned_to_person_id == dad.id
        assert txn.assignment_method == "manual"
        assert txn.needs_review is False

    assert "Assigned to Dad" in query.text
    assert query.reply_markup.inline_keyboard[0][0].callback_data == f"undo_{transaction_id}"


@pytest.mark.asyncio
async def test_undo_callback_restores_review_queue(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        statement = create_statement(db)
        txn = create_transaction(db, statement, "UNDO TARGET", 25.5)
        transaction_id = txn.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)

    update, context, _ = make_callback(f"assign_{transaction_id}_{dad.id}")
    await handlers.handle_callback(update, context)

    undo_update, undo_context, undo_query = make_callback(f"undo_{transaction_id}")
    await handlers.handle_callback(undo_update, undo_context)

    with session_local() as db:
        txn = db.query(Transaction).filter(Transaction.id == transaction_id).one()
        assert txn.assigned_to_person_id is None
        assert txn.needs_review is True
        assert txn.assignment_method == "category_review"
        assert txn.reviewed_at is None

    assert "Moved back to /review" in undo_query.text


@pytest.mark.asyncio
async def test_shared_expense_flow_requires_two_people_and_saves_equal_split(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        dad, wife, _ = create_people(db)
        statement = create_statement(db)
        txn = create_transaction(db, statement, "SHARED DINNER", 40.0)
        transaction_id = txn.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    context = SimpleNamespace(user_data={})

    share_query = FakeQuery(f"share_{transaction_id}")
    await handlers.handle_callback(SimpleNamespace(callback_query=share_query), context)
    assert "Shared expense mode" in share_query.text

    toggle_one_query = FakeQuery(f"sharetoggle_{transaction_id}_{dad.id}")
    await handlers.handle_callback(SimpleNamespace(callback_query=toggle_one_query), context)
    assert "Selected: Dad" in toggle_one_query.text

    invalid_save_query = FakeQuery(f"sharesave_{transaction_id}")
    await handlers.handle_callback(SimpleNamespace(callback_query=invalid_save_query), context)
    assert "Select at least 2 people" in invalid_save_query.text

    toggle_two_query = FakeQuery(f"sharetoggle_{transaction_id}_{wife.id}")
    await handlers.handle_callback(SimpleNamespace(callback_query=toggle_two_query), context)
    assert "Selected: Dad, Wife" in toggle_two_query.text

    save_query = FakeQuery(f"sharesave_{transaction_id}")
    await handlers.handle_callback(SimpleNamespace(callback_query=save_query), context)

    with session_local() as db:
        txn = db.query(Transaction).filter(Transaction.id == transaction_id).one()
        splits = list(txn.transaction_splits)
        assert txn.assignment_method == "shared_manual"
        assert txn.needs_review is False
        assert txn.assigned_to_person_id is None
        assert len(splits) == 2
        assert [split.person_id for split in splits] == [dad.id, wife.id]
        assert [split.split_amount for split in splits] == [20.0, 20.0]

    assert "Shared expense saved" in save_query.text
    assert save_query.reply_markup.inline_keyboard[0][0].callback_data == f"undo_{transaction_id}"


@pytest.mark.asyncio
async def test_locked_transactions_reject_undo_and_shared(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        dad, wife, _ = create_people(db)
        statement = create_statement(db)
        txn = create_transaction(
            db,
            statement,
            "LOCKED ITEM",
            90.0,
            needs_review=False,
            assignment_method="manual",
            review_origin_method="category_review",
            assigned_to_person_id=dad.id,
        )
        bill = Bill(
            person_id=dad.id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
            total_amount=90.0,
            status="finalized",
        )
        db.add(bill)
        db.flush()
        db.add(BillLineItem(bill_id=bill.id, transaction_id=txn.id, amount=90.0, description=txn.merchant_name))
        db.commit()
        transaction_id = txn.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)

    undo_query = FakeQuery(f"undo_{transaction_id}")
    await handlers.handle_callback(SimpleNamespace(callback_query=undo_query), SimpleNamespace(user_data={}))
    assert "finalized or paid bill" in undo_query.text

    shared_context = SimpleNamespace(user_data={handlers.SHARED_REVIEW_STATES_KEY: {transaction_id: [dad.id, wife.id]}})
    shared_query = FakeQuery(f"sharesave_{transaction_id}")
    await handlers.handle_callback(SimpleNamespace(callback_query=shared_query), shared_context)
    assert "finalized or paid bill" in shared_query.text


def test_equal_split_remainder_goes_to_last_selected_person():
    session_local = make_session_local()
    with session_local() as db:
        dad, wife, self_person = create_people(db)
        statement = create_statement(db)
        txn = create_transaction(db, statement, "REMAINDER TEST", 10.0)

        assign_transaction_equal_split(db, txn, [dad.id, wife.id, self_person.id])

        db.refresh(txn)
        assert [split.split_amount for split in txn.transaction_splits] == [3.33, 3.33, 3.34]


def test_shared_transactions_render_in_separate_bill_section():
    session_local = make_session_local()
    with session_local() as db:
        dad, _, self_person = create_people(db)
        statement = create_statement(db)
        create_card_direct_rule(db, self_person, statement.card_last_4)
        direct_txn = create_transaction(
            db,
            statement,
            "DIRECT CHARGE",
            18.5,
            needs_review=False,
            assignment_method="manual",
            review_origin_method=None,
            assigned_to_person_id=dad.id,
        )
        shared_txn = create_transaction(db, statement, "SHARED DINNER", 12.0)
        assign_transaction_equal_split(db, shared_txn, [dad.id, self_person.id])

        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-03")
        message = generator.format_bill_message(bill.id)

        assert "Credit Card Charges:" in message
        assert "Shared Expenses:" in message
        assert message.index("DIRECT CHARGE") < message.index("Shared Expenses:")
        assert message.index("SHARED DINNER") > message.index("Shared Expenses:")
        assert "(UOB ****1234, Self card)" in message


def test_bill_message_appends_card_owner_to_direct_and_shared_lines():
    session_local = make_session_local()
    with session_local() as db:
        dad, _, self_person = create_people(db)
        statement = create_statement(db)
        create_card_direct_rule(db, self_person, statement.card_last_4)

        direct_txn = create_transaction(
            db,
            statement,
            "OWNER DIRECT",
            33.3,
            needs_review=False,
            assignment_method="manual",
            review_origin_method=None,
            assigned_to_person_id=dad.id,
        )
        shared_txn = create_transaction(db, statement, "OWNER SHARED", 12.0)
        assign_transaction_equal_split(db, shared_txn, [dad.id, self_person.id])

        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-03")
        message = generator.format_bill_message(bill.id)

        direct_line = next(line for line in message.splitlines() if "OWNER DIRECT" in line)
        shared_line = next(line for line in message.splitlines() if "OWNER SHARED" in line)
        assert "(UOB ****1234, Self card)" in direct_line
        assert "(UOB ****1234, Self card)" in shared_line


def test_bill_message_hides_owner_when_card_belongs_to_billed_person():
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        statement = create_statement(db)
        create_card_direct_rule(db, dad, statement.card_last_4)

        create_transaction(
            db,
            statement,
            "OWN CARD",
            44.0,
            needs_review=False,
            assignment_method="manual",
            review_origin_method=None,
            assigned_to_person_id=dad.id,
        )

        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-03")
        message = generator.format_bill_message(bill.id)

        line = next(line for line in message.splitlines() if "OWN CARD" in line)
        assert "(UOB ****1234)" in line
        assert "Dad card" not in line


def test_bill_message_keeps_old_card_suffix_when_owner_unknown():
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        statement = create_statement(db)

        create_transaction(
            db,
            statement,
            "UNKNOWN OWNER",
            18.5,
            needs_review=False,
            assignment_method="manual",
            review_origin_method=None,
            assigned_to_person_id=dad.id,
        )

        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-03")
        message = generator.format_bill_message(bill.id)

        line = next(line for line in message.splitlines() if "UNKNOWN OWNER" in line)
        assert "(UOB ****1234)" in line
        assert "card)" not in line


def test_undo_deletes_affected_draft_bills():
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        statement = create_statement(db)
        txn = create_transaction(db, statement, "DELETE DRAFT BILL", 55.0)

        assign_transaction_to_person(db, txn, dad.id)
        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-03")
        assert bill is not None
        assert db.query(Bill).count() == 1

        outcome = undo_review_assignment(db, txn)

        assert outcome.affected_draft_bill_ids == [bill.id]
        assert db.query(Bill).count() == 0
        db.refresh(txn)
        assert txn.needs_review is True
