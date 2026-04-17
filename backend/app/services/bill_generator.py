"""
Bill Generator Service

Assembles per-person monthly bills from transactions, refunds, and recurring charges.
"""
import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Person, Transaction, Bill, BillLineItem, ManualBill, TransactionSplit
from app.services.card_owner import format_statement_card_label
from app.services.bill_sheets_exporter import BillSheetsExporter

logger = logging.getLogger(__name__)


class BillGenerator:
    """Generates and manages monthly bills per person."""

    def __init__(self, db: Session):
        self.db = db

    def generate_bill(self, person_id: int, billing_month: str) -> Optional[Bill]:
        """
        Generate (or regenerate) a bill for a person and billing month.

        If a draft bill already exists, it is deleted and recreated.
        Finalized and paid bills are not regenerated (returns existing).

        Args:
            person_id: ID of the person to bill
            billing_month: Format "YYYY-MM"

        Returns:
            Bill object, or None if no billable items exist
        """
        person = self.db.query(Person).filter(Person.id == person_id).first()
        if not person:
            raise ValueError(f"Person {person_id} not found")

        # Parse billing month into period dates
        year, month = int(billing_month[:4]), int(billing_month[5:7])
        period_start = date(year, month, 1)
        if month == 12:
            period_end = date(year + 1, 1, 1)
        else:
            period_end = date(year, month + 1, 1)

        # Check for existing bill
        existing = self.db.query(Bill).filter(
            Bill.person_id == person_id,
            Bill.period_start == period_start,
        ).first()

        if existing and existing.status in {"finalized", "paid"}:
            return existing

        # Delete existing draft to regenerate
        if existing:
            self.db.delete(existing)
            self.db.flush()

        # Gather transactions assigned to this person for this billing month
        transactions = (
            self.db.query(Transaction)
            .filter(
                Transaction.assigned_to_person_id == person_id,
                Transaction.billing_month == billing_month,
            )
            .order_by(Transaction.transaction_date)
            .all()
        )

        shared_splits = (
            self.db.query(TransactionSplit)
            .join(Transaction, Transaction.id == TransactionSplit.transaction_id)
            .filter(
                TransactionSplit.person_id == person_id,
                Transaction.billing_month == billing_month,
            )
            .order_by(Transaction.transaction_date, TransactionSplit.sort_order)
            .all()
        )

        # Gather manual bills for this person and month
        manual_bills = (
            self.db.query(ManualBill)
            .filter(
                ManualBill.person_id == person_id,
                ManualBill.billing_month == billing_month,
            )
            .all()
        )

        if not transactions and not shared_splits and not manual_bills:
            return None

        # Calculate total
        txn_total = sum(t.amount for t in transactions)
        shared_total = sum(split.split_amount for split in shared_splits)
        manual_total = sum(m.amount for m in manual_bills)
        total = txn_total + shared_total + manual_total

        # Create bill
        bill = Bill(
            person_id=person_id,
            period_start=period_start,
            period_end=period_end,
            total_amount=round(total, 2),
            status="draft",
        )
        self.db.add(bill)
        self.db.flush()

        # Create line items for transactions
        for txn in transactions:
            desc = txn.merchant_name
            if txn.is_refund:
                desc = f"REFUND: {desc}"
            line = BillLineItem(
                bill_id=bill.id,
                transaction_id=txn.id,
                amount=txn.amount,
                description=desc,
            )
            self.db.add(line)

        for split in shared_splits:
            desc = split.transaction.merchant_name if split.transaction else "Shared expense"
            if split.transaction and split.transaction.is_refund:
                desc = f"REFUND: {desc}"
            line = BillLineItem(
                bill_id=bill.id,
                transaction_id=split.transaction_id,
                amount=split.split_amount,
                description=desc,
            )
            self.db.add(line)

        # Create line items for manual bills
        for mb in manual_bills:
            line = BillLineItem(
                bill_id=bill.id,
                manual_bill_id=mb.id,
                amount=mb.amount,
                description=mb.description,
            )
            self.db.add(line)

        self.db.commit()
        self.db.refresh(bill)

        logger.info(
            "Generated bill for %s %s: $%.2f (%d txns, %d shared, %d manual)",
            person.name, billing_month, total, len(transactions), len(shared_splits), len(manual_bills),
        )

        return bill

    def finalize_bill(self, bill_id: int) -> Bill:
        """
        Finalize a bill (lock it from further changes).

        Requires all transactions for this person/month to be reviewed.

        Raises:
            ValueError: If bill not found, already finalized, or has unreviewed transactions
        """
        bill = self.db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            raise ValueError("Bill not found")
        if bill.status == "paid":
            raise ValueError("Paid bills cannot be finalized again")
        if bill.status == "finalized":
            raise ValueError("Bill is already finalized")

        billing_month = f"{bill.period_start.year:04d}-{bill.period_start.month:02d}"

        # Check for unreviewed transactions
        pending = self.db.query(Transaction).filter(
            Transaction.assigned_to_person_id == bill.person_id,
            Transaction.billing_month == billing_month,
            Transaction.needs_review == True,
        ).count()

        if pending > 0:
            raise ValueError(
                f"Cannot finalize: {pending} transaction(s) still pending review"
            )

        bill.status = "finalized"
        bill.finalized_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(bill)
        self._export_finalized_bill(bill)

        return bill

    def mark_bill_paid(self, bill_id: int) -> Bill:
        """Mark a finalized bill as paid."""
        bill = self.db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            raise ValueError("Bill not found")
        if bill.status == "paid":
            raise ValueError("Bill is already paid")
        if bill.status != "finalized":
            raise ValueError("Only finalized bills can be marked paid")

        bill.status = "paid"
        bill.paid_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(bill)

        return bill

    def mark_bill_unpaid(self, bill_id: int) -> Bill:
        """Revert a paid bill back to finalized."""
        bill = self.db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            raise ValueError("Bill not found")
        if bill.status != "paid":
            raise ValueError("Only paid bills can be marked unpaid")

        bill.status = "finalized"
        bill.paid_at = None
        self.db.commit()
        self.db.refresh(bill)

        return bill

    def format_bill_message(self, bill_id: int) -> str:
        """
        Format a bill as a text message for Telegram.

        Args:
            bill_id: ID of the bill

        Returns:
            Formatted text string
        """
        bill = self.db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return "Bill not found."

        person = bill.person
        billing_month = f"{bill.period_start.year:04d}-{bill.period_start.month:02d}"

        lines = [f"Bill for {person.name} -- {billing_month}\n"]

        # Separate line items into categories
        txn_items = []
        refund_items = []
        shared_items = []
        recurring_items = []
        manually_added_items = []

        for item in bill.line_items:
            if item.manual_bill_id:
                manual_bill = item.manual_bill
                manual_type = manual_bill.manual_type if manual_bill else ManualBill.TYPE_RECURRING
                if manual_type == ManualBill.TYPE_MANUALLY_ADDED:
                    manually_added_items.append(item)
                else:
                    recurring_items.append(item)
            elif item.transaction and item.transaction.is_refund:
                refund_items.append(item)
            elif item.transaction and item.transaction.transaction_splits:
                shared_items.append(item)
            else:
                txn_items.append(item)

        # Credit card charges
        if txn_items:
            lines.append("Credit Card Charges:")
            for item in txn_items:
                txn = item.transaction
                date_str = txn.transaction_date.strftime("%m/%d") if txn else ""
                card_str = format_statement_card_label(
                    self.db,
                    txn.statement if txn else None,
                    bill.person,
                )
                lines.append(f"  {date_str} {item.description:<30s} ${item.amount:>8.2f}{card_str}")
            lines.append("")

        # Refunds
        if refund_items:
            lines.append("Refunds:")
            for item in refund_items:
                txn = item.transaction
                date_str = txn.transaction_date.strftime("%m/%d") if txn else ""
                desc = item.description
                # Annotate cross-month refunds with the original charge's billing month
                if txn and txn.original_transaction and txn.original_transaction.billing_month != billing_month:
                    desc += f" (from {txn.original_transaction.billing_month})"
                lines.append(f"  {date_str} {desc:<30s} -${abs(item.amount):>7.2f}")
            lines.append("")

        # Monthly recurring
        if recurring_items:
            lines.append("Monthly Recurring:")
            for item in recurring_items:
                lines.append(f"  {item.description:<36s} ${item.amount:>8.2f}")
            lines.append("")

        if manually_added_items:
            lines.append("Manually Added:")
            for item in manually_added_items:
                lines.append(f"  {item.description:<36s} ${item.amount:>8.2f}")
            lines.append("")

        if shared_items:
            lines.append("Shared Expenses:")
            for item in shared_items:
                txn = item.transaction
                date_str = txn.transaction_date.strftime("%m/%d") if txn else ""
                card_str = format_statement_card_label(
                    self.db,
                    txn.statement if txn else None,
                    bill.person,
                )
                lines.append(f"  {date_str} {item.description:<30s} ${item.amount:>8.2f}{card_str}")
            lines.append("")

        # Total
        lines.append("-" * 48)
        lines.append(f"{'Total:':<36s} ${bill.total_amount:>8.2f}")
        lines.append(f"\nStatus: {bill.status}")
        if bill.finalized_at:
            lines.append(f"Finalized at: {bill.finalized_at.strftime('%Y-%m-%d %H:%M UTC')}")
        if bill.paid_at:
            lines.append(f"Paid at: {bill.paid_at.strftime('%Y-%m-%d %H:%M UTC')}")

        return "\n".join(lines)

    def _export_finalized_bill(self, bill: Bill) -> None:
        """Best-effort export of finalized bill summaries to Google Sheets."""
        try:
            BillSheetsExporter().export_finalized_bill(bill)
        except Exception:
            logger.exception("Failed to export finalized bill %s to Google Sheets", bill.id)
