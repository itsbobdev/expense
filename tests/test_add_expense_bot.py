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
from app.models import Bill, ManualBill, Person
from app.services.bill_generator import BillGenerator


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


class FakeMessage:
    def __init__(self, text: str | None = None):
        self.text = text
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


@pytest.mark.asyncio
async def test_add_expense_command_initializes_prompt_state(monkeypatch):
    message = FakeMessage()
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={"stale": True})

    monkeypatch.setattr(handlers, "_current_singapore_billing_month", lambda: "2026-04")

    await handlers.add_expense_command(update, context)

    assert context.user_data[handlers.ADD_EXPENSE_STATE_KEY] == {
        "step": "amount",
        "amount": None,
        "description": None,
        "billing_month": "2026-04",
    }
    assert "Send the amount as a positive number" in message.calls[-1]["text"]


@pytest.mark.asyncio
async def test_add_expense_invalid_amount_retries_without_saving(monkeypatch):
    session_local = make_session_local()
    monkeypatch.setattr(handlers, "SessionLocal", session_local)

    message = FakeMessage("abc")
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={handlers.ADD_EXPENSE_STATE_KEY: handlers._default_add_expense_state()})

    await handlers.handle_text_message(update, context)

    assert context.user_data[handlers.ADD_EXPENSE_STATE_KEY]["step"] == "amount"
    assert "Invalid amount" in message.calls[-1]["text"]
    with session_local() as db:
        assert db.query(ManualBill).count() == 0


@pytest.mark.asyncio
async def test_add_expense_empty_description_retries(monkeypatch):
    message = FakeMessage("   ")
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={
        handlers.ADD_EXPENSE_STATE_KEY: {
            "step": "description",
            "amount": 12.5,
            "description": None,
            "billing_month": "2026-04",
        }
    })

    await handlers.handle_text_message(update, context)

    assert context.user_data[handlers.ADD_EXPENSE_STATE_KEY]["step"] == "description"
    assert "Description cannot be empty" in message.calls[-1]["text"]


@pytest.mark.asyncio
async def test_add_expense_invalid_month_retries(monkeypatch):
    message = FakeMessage("2026-13")
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={
        handlers.ADD_EXPENSE_STATE_KEY: {
            "step": "billing_month",
            "amount": 12.5,
            "description": "Lunch",
            "billing_month": "2026-04",
        }
    })

    monkeypatch.setattr(handlers, "_current_singapore_billing_month", lambda: "2026-04")

    await handlers.handle_text_message(update, context)

    assert context.user_data[handlers.ADD_EXPENSE_STATE_KEY]["step"] == "billing_month"
    assert "Billing month must be in YYYY-MM format." not in message.calls[-1]["text"]
    assert "Enter billing month as YYYY-MM." in message.calls[-1]["text"]


@pytest.mark.asyncio
async def test_add_expense_skip_uses_default_month_and_saves_manual_bill(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        dad, wife, self_person = create_people(db)
        selected_person_id = wife.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    monkeypatch.setattr(handlers, "_current_singapore_billing_month", lambda: "2026-04")

    context = SimpleNamespace(user_data={})

    await handlers.add_expense_command(SimpleNamespace(message=FakeMessage()), context)

    amount_message = FakeMessage("12.50")
    await handlers.handle_text_message(SimpleNamespace(message=amount_message), context)
    assert context.user_data[handlers.ADD_EXPENSE_STATE_KEY]["step"] == "description"

    desc_message = FakeMessage("Team lunch")
    await handlers.handle_text_message(SimpleNamespace(message=desc_message), context)
    assert context.user_data[handlers.ADD_EXPENSE_STATE_KEY]["step"] == "billing_month"

    month_message = FakeMessage("skip")
    await handlers.handle_text_message(SimpleNamespace(message=month_message), context)
    assert context.user_data[handlers.ADD_EXPENSE_STATE_KEY]["step"] == "person"
    reply_markup = month_message.calls[-1]["reply_markup"]
    callback_values = [button.callback_data for row in reply_markup.inline_keyboard for button in row]
    assert f"addexpense_person_{selected_person_id}" in callback_values
    assert "addexpense_cancel" in callback_values

    query = FakeQuery(f"addexpense_person_{selected_person_id}")
    await handlers.handle_callback(SimpleNamespace(callback_query=query), context)

    with session_local() as db:
        bills = db.query(ManualBill).all()
        assert len(bills) == 1
        assert bills[0].amount == 12.5
        assert bills[0].description == "Team lunch"
        assert bills[0].billing_month == "2026-04"
        assert bills[0].person_id == selected_person_id
        assert bills[0].manual_type == ManualBill.TYPE_MANUALLY_ADDED

    assert handlers.ADD_EXPENSE_STATE_KEY not in context.user_data
    assert "Manual expense saved" in query.text
    assert "Category: Manually Added" in query.text
    assert "Assigned to: Wife" in query.text


@pytest.mark.asyncio
async def test_cancel_command_clears_add_expense_state_and_does_not_save(monkeypatch):
    session_local = make_session_local()
    monkeypatch.setattr(handlers, "SessionLocal", session_local)

    message = FakeMessage()
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={
        handlers.ADD_EXPENSE_STATE_KEY: {
            "step": "description",
            "amount": 19.99,
            "description": None,
            "billing_month": "2026-04",
        }
    })

    await handlers.cancel_command(update, context)

    assert handlers.ADD_EXPENSE_STATE_KEY not in context.user_data
    assert message.calls[-1]["text"] == "Add expense cancelled."
    with session_local() as db:
        assert db.query(ManualBill).count() == 0


@pytest.mark.asyncio
async def test_add_expense_state_isolated_from_blacklist_flow(monkeypatch):
    message = FakeMessage("15.25")
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={
        "adding_blacklist": True,
        handlers.ADD_EXPENSE_STATE_KEY: {
            "step": "amount",
            "amount": None,
            "description": None,
            "billing_month": "2026-04",
        },
    })

    await handlers.handle_text_message(update, context)

    state = context.user_data[handlers.ADD_EXPENSE_STATE_KEY]
    assert state["amount"] == 15.25
    assert state["step"] == "description"
    assert context.user_data["adding_blacklist"] is True
    assert message.calls[-1]["text"] == "Enter a description for this expense."


def test_manual_bill_created_via_model_appears_in_generated_bill():
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        manual_bill = ManualBill(
            person_id=dad.id,
            amount=88.4,
            description="Parking reimbursement",
            billing_month="2026-04",
            manual_type=ManualBill.TYPE_MANUALLY_ADDED,
        )
        db.add(manual_bill)
        db.commit()

        bill = BillGenerator(db).generate_bill(dad.id, "2026-04")

        assert bill is not None
        assert bill.total_amount == 88.4
        assert [item.description for item in bill.line_items] == ["Parking reimbursement"]
        assert bill.line_items[0].manual_bill_id == manual_bill.id
        assert "Manually Added:" in BillGenerator(db).format_bill_message(bill.id)


def test_manual_bill_defaults_to_recurring_type():
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        manual_bill = ManualBill(
            person_id=dad.id,
            amount=20.0,
            description="HDB Season Parking",
            billing_month="2026-04",
        )
        db.add(manual_bill)
        db.commit()
        db.refresh(manual_bill)

        assert manual_bill.manual_type == ManualBill.TYPE_RECURRING


def test_bill_message_separates_recurring_and_manually_added_items():
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        db.add_all([
            ManualBill(
                person_id=dad.id,
                amount=110.0,
                description="HDB Season Parking",
                billing_month="2026-04",
                manual_type=ManualBill.TYPE_RECURRING,
            ),
            ManualBill(
                person_id=dad.id,
                amount=0.01,
                description="TEST",
                billing_month="2026-04",
                manual_type=ManualBill.TYPE_MANUALLY_ADDED,
            ),
        ])
        db.commit()

        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-04")
        text = generator.format_bill_message(bill.id)

        assert "Monthly Recurring:" in text
        assert "HDB Season Parking" in text
        assert "Manually Added:" in text
        assert "TEST" in text


def test_bill_response_includes_remove_button_for_manually_added_items():
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        db.add_all([
            ManualBill(
                person_id=dad.id,
                amount=110.0,
                description="HDB Season Parking",
                billing_month="2026-04",
                manual_type=ManualBill.TYPE_RECURRING,
            ),
            ManualBill(
                person_id=dad.id,
                amount=0.01,
                description="TEST",
                billing_month="2026-04",
                manual_type=ManualBill.TYPE_MANUALLY_ADDED,
            ),
        ])
        db.commit()

        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-04")
        _, keyboard = handlers._build_bill_response(db, generator, bill)
        manual_bill_id = next(
            item.manual_bill_id
            for item in bill.line_items
            if item.manual_bill and item.manual_bill.manual_type == ManualBill.TYPE_MANUALLY_ADDED
        )

        callback_values = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        assert f"bill_remove_{bill.id}_{manual_bill_id}" in callback_values


@pytest.mark.asyncio
async def test_remove_manually_added_expense_regenerates_draft_bill(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        recurring = ManualBill(
            person_id=dad.id,
            amount=110.0,
            description="HDB Season Parking",
            billing_month="2026-04",
            manual_type=ManualBill.TYPE_RECURRING,
        )
        added = ManualBill(
            person_id=dad.id,
            amount=0.01,
            description="TEST",
            billing_month="2026-04",
            manual_type=ManualBill.TYPE_MANUALLY_ADDED,
        )
        db.add_all([recurring, added])
        db.commit()

        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-04")
        bill_id = bill.id
        added_id = added.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    query = FakeQuery(f"bill_remove_{bill_id}_{added_id}")

    await handlers.handle_callback(SimpleNamespace(callback_query=query), SimpleNamespace(user_data={}))

    with session_local() as db:
        remaining = db.query(ManualBill).order_by(ManualBill.id).all()
        assert [item.description for item in remaining] == ["HDB Season Parking"]
        regenerated_bill = db.query(Bill).one()
        assert regenerated_bill.total_amount == 110.0

    assert "Manually Added:" not in query.text
    assert "TEST" not in query.text
    assert "Monthly Recurring:" in query.text


@pytest.mark.asyncio
async def test_remove_last_manually_added_expense_shows_empty_state(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        added = ManualBill(
            person_id=dad.id,
            amount=0.01,
            description="TEST",
            billing_month="2026-04",
            manual_type=ManualBill.TYPE_MANUALLY_ADDED,
        )
        db.add(added)
        db.commit()

        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-04")
        bill_id = bill.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    query = FakeQuery(f"bill_remove_{bill_id}_{added.id}")

    await handlers.handle_callback(SimpleNamespace(callback_query=query), SimpleNamespace(user_data={}))

    with session_local() as db:
        assert db.query(ManualBill).count() == 0
        assert db.query(Bill).count() == 0

    assert "Removed manually added expense: TEST" in query.text
    assert "No billable items remain for 2026-04." in query.text


@pytest.mark.asyncio
async def test_remove_manually_added_expense_rejects_finalized_bill(monkeypatch):
    session_local = make_session_local()
    with session_local() as db:
        dad, _, _ = create_people(db)
        added = ManualBill(
            person_id=dad.id,
            amount=0.01,
            description="TEST",
            billing_month="2026-04",
            manual_type=ManualBill.TYPE_MANUALLY_ADDED,
        )
        db.add(added)
        db.commit()

        generator = BillGenerator(db)
        bill = generator.generate_bill(dad.id, "2026-04")
        bill.status = "finalized"
        db.commit()
        bill_id = bill.id

    monkeypatch.setattr(handlers, "SessionLocal", session_local)
    query = FakeQuery(f"bill_remove_{bill_id}_{added.id}")

    await handlers.handle_callback(SimpleNamespace(callback_query=query), SimpleNamespace(user_data={}))

    with session_local() as db:
        assert db.query(ManualBill).count() == 1

    assert "Only draft bills can remove manually added expenses" in query.text
