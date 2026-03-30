from datetime import date
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import (
    AssignmentRule,
    Bill,
    BillLineItem,
    ManualBill,
    Person,
    Statement,
    Transaction,
    TransactionSplit,
)
from app.services.bill_generator import BillGenerator
from app.services.bill_sheets_exporter import BillSheetsExporter


class _FakeValuesApi:
    def __init__(self, state):
        self.state = state

    def get(self, spreadsheetId, range):
        self.state["calls"].append(("get_values", spreadsheetId, range))
        values = self.state["headers"].get(range, [])
        return _FakeExecute({"values": values})

    def update(self, spreadsheetId, range, valueInputOption, body):
        self.state["calls"].append(("update_values", spreadsheetId, range, valueInputOption, body))
        self.state["headers"][range] = body["values"]
        return _FakeExecute({})

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        self.state["calls"].append(("append_values", spreadsheetId, range, valueInputOption, insertDataOption, body))
        self.state["appended"].append((range, body["values"]))
        return _FakeExecute({})


class _FakeSpreadsheetsApi:
    def __init__(self, state):
        self.state = state
        self._values = _FakeValuesApi(state)

    def get(self, spreadsheetId):
        self.state["calls"].append(("get_spreadsheet", spreadsheetId))
        payload = {
            "sheets": [{"properties": {"title": name}} for name in sorted(self.state["sheet_names"])]
        }
        return _FakeExecute(payload)

    def batchUpdate(self, spreadsheetId, body):
        self.state["calls"].append(("batch_update", spreadsheetId, body))
        title = body["requests"][0]["addSheet"]["properties"]["title"]
        self.state["sheet_names"].add(title)
        return _FakeExecute({})

    def values(self):
        return self._values


class _FakeSheetsService:
    def __init__(self, state):
        self.state = state
        self._spreadsheets = _FakeSpreadsheetsApi(state)

    def spreadsheets(self):
        return self._spreadsheets


class _FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


def _build_session():
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal


def _make_bill_fixture(db):
    billed_person = Person(name="foo_wah_liang", relationship_type="parent", is_auto_created=False)
    other_person = Person(name="chan_zelin", relationship_type="spouse", is_auto_created=False)
    db.add_all([billed_person, other_person])
    db.flush()

    assignment_rule = AssignmentRule(
        priority=100,
        rule_type="card_direct",
        conditions={"card_last_4": "9103"},
        assign_to_person_id=other_person.id,
        is_active=True,
    )
    db.add(assignment_rule)

    bill = Bill(
        person_id=billed_person.id,
        period_start=date(2026, 2, 1),
        period_end=date(2026, 3, 1),
        total_amount=123.45,
        status="finalized",
    )
    db.add(bill)
    db.flush()

    charge_statement = Statement(
        filename="charge.json",
        bank_name="Maybank",
        card_last_4="9103",
        statement_date=date(2026, 2, 25),
        billing_month="2026-02",
        raw_file_path="charge.json",
    )
    db.add(charge_statement)
    db.flush()

    charge_txn = Transaction(
        statement_id=charge_statement.id,
        billing_month="2026-02",
        transaction_date=date(2026, 2, 1),
        merchant_name="IKEA",
        amount=25.00,
        assigned_to_person_id=billed_person.id,
        is_refund=False,
    )
    refund_txn = Transaction(
        statement_id=charge_statement.id,
        billing_month="2026-02",
        transaction_date=date(2026, 2, 2),
        merchant_name="SHOPEE SINGAPORE MP",
        amount=-7.11,
        assigned_to_person_id=billed_person.id,
        is_refund=True,
    )
    shared_txn = Transaction(
        statement_id=charge_statement.id,
        billing_month="2026-02",
        transaction_date=date(2026, 2, 3),
        merchant_name="NTUC FAIRPRICE APP PAY",
        amount=30.00,
        assigned_to_person_id=other_person.id,
        is_refund=False,
    )
    db.add_all([charge_txn, refund_txn, shared_txn])
    db.flush()

    split = TransactionSplit(
        transaction_id=shared_txn.id,
        person_id=billed_person.id,
        split_amount=12.50,
        sort_order=0,
    )
    manual_bill = ManualBill(
        person_id=billed_person.id,
        amount=92.06,
        description="HDB Season Parking",
        billing_month="2026-02",
    )
    db.add_all([split, manual_bill])
    db.flush()

    line_items = [
        BillLineItem(bill_id=bill.id, transaction_id=charge_txn.id, amount=25.00, description="IKEA"),
        BillLineItem(
            bill_id=bill.id,
            transaction_id=refund_txn.id,
            amount=-7.11,
            description="REFUND: SHOPEE SINGAPORE MP",
        ),
        BillLineItem(
            bill_id=bill.id,
            transaction_id=shared_txn.id,
            amount=12.50,
            description="NTUC FAIRPRICE APP PAY",
        ),
        BillLineItem(
            bill_id=bill.id,
            manual_bill_id=manual_bill.id,
            amount=92.06,
            description="HDB Season Parking",
        ),
    ]
    db.add_all(line_items)
    db.commit()
    db.refresh(bill)
    return bill


def test_build_rows_includes_line_types_and_repeated_bill_metadata():
    SessionLocal = _build_session()
    with SessionLocal() as db:
        bill = _make_bill_fixture(db)

        rows = BillSheetsExporter()._build_rows(bill, exported_at="2026-03-30T12:00:00")

        assert len(rows) == 4
        assert [row[10] for row in rows] == [
            "charge",
            "refund",
            "shared",
            "manual_recurring",
        ]
        assert [row[16] for row in rows] == [
            "transaction",
            "transaction",
            "transaction_split",
            "manual_bill",
        ]
        assert all(row[1] == str(bill.id) for row in rows)
        assert all(row[2] == "foo_wah_liang" for row in rows)
        assert all(row[3] == "2026-02" for row in rows)
        assert rows[0][15] == "Maybank ****9103, chan_zelin card"
        assert rows[1][14] == "SHOPEE SINGAPORE MP"
        assert rows[2][13] == "12.50"
        assert rows[3][11] == ""
        assert rows[3][14] == ""


def test_export_finalized_bill_uses_person_tab_and_bootstraps_missing_worksheet(monkeypatch):
    SessionLocal = _build_session()
    state = {
        "sheet_names": set(),
        "headers": {},
        "appended": [],
        "calls": [],
    }

    with SessionLocal() as db:
        bill = _make_bill_fixture(db)
        exporter = BillSheetsExporter()
        exporter.enabled = True
        exporter.spreadsheet = "spreadsheet-id"
        exporter.service_account_json = "service-account.json"

        monkeypatch.setattr(exporter, "_build_service", lambda: _FakeSheetsService(state))

        assert exporter.export_finalized_bill(bill) is True

    assert "foo_wah_liang" in state["sheet_names"]
    assert state["headers"]["'foo_wah_liang'!A1:Q1"] == [BillSheetsExporter.HEADERS]
    assert state["appended"][0][0] == "'foo_wah_liang'!A:Q"
    assert len(state["appended"][0][1]) == 4
    assert ("batch_update", "spreadsheet-id", {"requests": [{"addSheet": {"properties": {"title": "foo_wah_liang"}}}]}) in state["calls"]


def test_export_finalized_bill_reuses_existing_worksheet_without_creating_it(monkeypatch):
    SessionLocal = _build_session()
    state = {
        "sheet_names": {"foo_wah_liang"},
        "headers": {"'foo_wah_liang'!A1:Q1": [BillSheetsExporter.HEADERS]},
        "appended": [],
        "calls": [],
    }

    with SessionLocal() as db:
        bill = _make_bill_fixture(db)
        exporter = BillSheetsExporter()
        exporter.enabled = True
        exporter.spreadsheet = "spreadsheet-id"
        exporter.service_account_json = "service-account.json"

        monkeypatch.setattr(exporter, "_build_service", lambda: _FakeSheetsService(state))

        assert exporter.export_finalized_bill(bill) is True

    assert not any(call[0] == "batch_update" for call in state["calls"])
    assert state["appended"][0][0] == "'foo_wah_liang'!A:Q"


def test_finalize_bill_exports_to_google_sheets(monkeypatch):
    SessionLocal = _build_session()
    with SessionLocal() as db:
        person = Person(name="foo_wah_liang", relationship_type="parent", is_auto_created=False)
        db.add(person)
        db.flush()

        bill = Bill(
            person_id=person.id,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 3, 1),
            total_amount=123.45,
            status="draft",
        )
        db.add(bill)
        db.commit()

        exported = []

        def fake_export(self, finalized_bill):
            exported.append((finalized_bill.id, finalized_bill.status))

        monkeypatch.setattr(BillGenerator, "_export_finalized_bill", fake_export)

        finalized = BillGenerator(db).finalize_bill(bill.id)

        assert finalized.status == "finalized"
        assert finalized.finalized_at is not None
        assert exported == [(bill.id, "finalized")]


def test_finalize_bill_tolerates_export_errors(monkeypatch):
    SessionLocal = _build_session()
    with SessionLocal() as db:
        person = Person(name="foo_wah_liang", relationship_type="parent", is_auto_created=False)
        db.add(person)
        db.flush()

        bill = Bill(
            person_id=person.id,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 3, 1),
            total_amount=123.45,
            status="draft",
        )
        db.add(bill)
        db.commit()

        def raise_export(self, finalized_bill):
            raise RuntimeError("google unavailable")

        monkeypatch.setattr(BillSheetsExporter, "export_finalized_bill", raise_export)

        finalized = BillGenerator(db).finalize_bill(bill.id)

        assert finalized.status == "finalized"
        assert finalized.finalized_at is not None
