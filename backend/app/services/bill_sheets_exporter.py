"""
Google Sheets export for finalized bills.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from app.config import settings
from app.models import Bill, BillLineItem
from app.services.card_owner import format_statement_card_label
from sqlalchemy.orm import object_session

logger = logging.getLogger(__name__)


class BillSheetsExporter:
    """Append finalized bill line items to per-person Google Sheets tabs."""

    HEADERS = [
        "exported_at",
        "bill_id",
        "person_name",
        "billing_month",
        "bill_status",
        "bill_total",
        "period_start",
        "period_end",
        "finalized_at",
        "line_item_id",
        "line_type",
        "transaction_date",
        "description",
        "amount",
        "merchant_name",
        "card_label",
        "source_kind",
    ]

    def __init__(self) -> None:
        self.enabled = settings.google_sheets_bill_export_enabled
        self.spreadsheet = settings.google_sheets_bill_export_spreadsheet.strip()
        self.service_account_json = settings.google_sheets_service_account_json.strip()

    def export_finalized_bill(self, bill: Bill) -> bool:
        """Append finalized bill line items. Returns True when rows are written."""
        if not self.enabled:
            return False

        spreadsheet_id = self._extract_spreadsheet_id(self.spreadsheet)
        if not spreadsheet_id:
            logger.warning("Skipping bill export: invalid Google Sheets spreadsheet setting")
            return False

        if not self.service_account_json:
            logger.warning("Skipping bill export: GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON is not configured")
            return False

        worksheet_name = self._worksheet_name_for_bill(bill)
        rows = self._build_rows(bill)
        if not rows:
            logger.info("Skipping bill export for bill %s: no line items to export", bill.id)
            return False

        service = self._build_service()
        self._ensure_worksheet(service, spreadsheet_id, worksheet_name)
        self._append_values(service, spreadsheet_id, worksheet_name, rows)
        logger.info(
            "Exported finalized bill %s to Google Sheet %s worksheet %s (%d rows)",
            bill.id,
            spreadsheet_id,
            worksheet_name,
            len(rows),
        )
        return True

    def _build_rows(self, bill: Bill, exported_at: Optional[str] = None) -> list[list[str]]:
        exported_at = exported_at or datetime.utcnow().isoformat()
        billing_month = f"{bill.period_start.year:04d}-{bill.period_start.month:02d}"
        person_name = bill.person.name if bill.person else ""
        finalized_at = bill.finalized_at.isoformat() if bill.finalized_at else ""
        period_start = bill.period_start.isoformat() if bill.period_start else ""
        period_end = bill.period_end.isoformat() if bill.period_end else ""
        db_session = object_session(bill)

        rows: list[list[str]] = []
        for item in bill.line_items:
            line_type, source_kind = self._classify_line_item(item)
            txn = item.transaction
            transaction_date = txn.transaction_date.isoformat() if txn else ""
            merchant_name = txn.merchant_name if txn else ""
            card_label = self._format_card_label(txn, bill.person, db_session)
            rows.append(
                [
                    exported_at,
                    str(bill.id),
                    person_name,
                    billing_month,
                    bill.status or "",
                    f"{bill.total_amount:.2f}",
                    period_start,
                    period_end,
                    finalized_at,
                    str(item.id),
                    line_type,
                    transaction_date,
                    item.description or "",
                    f"{item.amount:.2f}",
                    merchant_name,
                    card_label,
                    source_kind,
                ]
            )
        return rows

    def _build_service(self):
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials.from_service_account_file(
            self.service_account_json,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        return build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def _ensure_worksheet(self, service, spreadsheet_id: str, worksheet_name: str) -> None:
        metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheet_names = {
            sheet.get("properties", {}).get("title", "")
            for sheet in metadata.get("sheets", [])
        }
        if worksheet_name not in sheet_names:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": worksheet_name}}}]},
            ).execute()

        header_range = f"{self._quote_sheet_name(worksheet_name)}!A1:Q1"
        existing = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=header_range,
        ).execute()
        values = existing.get("values", [])
        if values[:1] != [self.HEADERS]:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=header_range,
                valueInputOption="RAW",
                body={"values": [self.HEADERS]},
            ).execute()

    def _append_values(
        self,
        service,
        spreadsheet_id: str,
        worksheet_name: str,
        values: list[list[str]],
    ) -> None:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{self._quote_sheet_name(worksheet_name)}!A:Q",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()

    @staticmethod
    def _worksheet_name_for_bill(bill: Bill) -> str:
        return bill.person.name if bill.person else "unknown"

    @staticmethod
    def _classify_line_item(item: BillLineItem) -> tuple[str, str]:
        if item.manual_bill_id:
            manual_bill = item.manual_bill
            if manual_bill and manual_bill.manual_type == manual_bill.TYPE_MANUALLY_ADDED:
                return "manual_added", "manual_bill"
            return "manual_recurring", "manual_bill"
        if item.transaction and item.transaction.is_refund:
            return "refund", "transaction"
        if item.transaction and item.transaction.transaction_splits:
            return "shared", "transaction_split"
        return "charge", "transaction"

    @staticmethod
    def _format_card_label(transaction, billed_person, db_session) -> str:
        statement = transaction.statement if transaction else None
        if not statement:
            return ""
        if db_session is not None:
            label = format_statement_card_label(db_session, statement, billed_person).strip()
            if label.startswith("(") and label.endswith(")"):
                return label[1:-1]
            return label
        bank_name = statement.bank_name or ""
        return f"{bank_name} ****{statement.card_last_4}".strip()

    @staticmethod
    def _quote_sheet_name(sheet_name: str) -> str:
        escaped = sheet_name.replace("'", "''")
        return f"'{escaped}'"

    @staticmethod
    def _extract_spreadsheet_id(value: str) -> Optional[str]:
        if not value:
            return None
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
        if match:
            return match.group(1)
        if re.fullmatch(r"[a-zA-Z0-9-_]+", value):
            return value
        return None
