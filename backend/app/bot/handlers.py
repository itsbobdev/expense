import re
import logging
from datetime import datetime, date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Person, Statement, Transaction, BlacklistCategory, Bill
from app.models.card_reward import CardReward
from app.services.bill_generator import BillGenerator
from app.services.categorizer import TransactionCategorizer
from app.services.refund_handler import RefundHandler
from app.services.importer import StatementImporter
from app.bot.keyboards import (
    get_review_keyboard, get_refund_review_keyboard, get_refund_person_keyboard,
    get_alert_keyboard, get_resolved_keyboard, get_bill_keyboard,
    get_review_result_keyboard, get_shared_expense_keyboard,
)
from app.config import settings
from app.services.review_assignment import (
    assign_transaction_equal_split,
    assign_transaction_to_person,
    get_review_persons,
    split_summary,
    undo_review_assignment,
)
from app.services.card_owner import get_card_owner_name

logger = logging.getLogger(__name__)
SHARED_REVIEW_STATES_KEY = "shared_review_states"


def _count_bill_pending_reviews(db: Session, bill: Bill) -> int:
    billing_month = f"{bill.period_start.year:04d}-{bill.period_start.month:02d}"
    return db.query(Transaction).filter(
        Transaction.billing_month == billing_month,
        Transaction.assigned_to_person_id == bill.person_id,
        Transaction.needs_review == True,
    ).count()


def _count_orphan_refunds(db: Session, billing_month: str) -> int:
    return db.query(Transaction).filter(
        Transaction.billing_month == billing_month,
        Transaction.needs_review == True,
        Transaction.assignment_method.in_(['refund_orphan', 'refund_ambiguous']),
    ).count()


def _build_bill_response(db: Session, generator: BillGenerator, bill: Bill) -> tuple[str, object]:
    text = generator.format_bill_message(bill.id)
    pending = _count_bill_pending_reviews(db, bill)

    if pending > 0:
        text += f"\n\nWarning: {pending} transaction(s) still pending review."

    billing_month = f"{bill.period_start.year:04d}-{bill.period_start.month:02d}"
    orphan_refunds = _count_orphan_refunds(db, billing_month)
    if orphan_refunds > 0:
        text += (
            f"\n\nWarning: {orphan_refunds} orphan refund(s) in {billing_month} "
            f"not yet matched. Run /refund {billing_month} to resolve."
        )

    keyboard = get_bill_keyboard(bill.id, bill.status, can_finalize=(pending == 0))
    logger.info(
        "Bill response built: bill_id=%s status=%s pending=%s orphan_refunds=%s keyboard=%s",
        bill.id,
        bill.status,
        pending,
        orphan_refunds,
        keyboard.to_dict() if keyboard else None,
    )
    return text, keyboard


def _find_persons_for_bill_filter(db: Session, person_filter: str) -> list[Person]:
    """Match person names while treating spaces, hyphens, and underscores equivalently."""
    normalized_filter = re.sub(r"[-_\s]+", "", person_filter).lower()
    persons = (
        db.query(Person)
        .filter(Person.is_auto_created == False)
        .order_by(Person.name)
        .all()
    )
    return [
        person for person in persons
        if normalized_filter in re.sub(r"[-_\s]+", "", person.name).lower()
    ]


def _build_review_transaction_text(
    txn: Transaction,
    index: int | None = None,
    total: int | None = None,
    show_billing_month: bool = False,
) -> str:
    card_info = ""
    if txn.statement:
        card_info = f"Card: {txn.statement.bank_name or ''} ****{txn.statement.card_last_4}"

    category_info = ""
    if txn.categories:
        category_info = f"Category: {', '.join(txn.categories)}"

    method_info = ""
    if txn.assignment_method:
        method_info = f"Reason: {txn.assignment_method}"

    amount_str = f"-${abs(txn.amount):.2f}" if txn.amount < 0 else f"${txn.amount:.2f}"
    prefix = ""
    if index is not None and total is not None:
        prefix = f"{index}/{total}: "

    lines = [f"{prefix}{txn.merchant_name} {amount_str}"]
    if card_info:
        lines.append(card_info)
    if category_info:
        lines.append(category_info)
    if method_info:
        lines.append(method_info)
    if show_billing_month and txn.billing_month:
        lines.append(f"Billing month: {txn.billing_month}")
    lines.append(f"Date: {txn.transaction_date}")
    return "\n".join(lines)


def _build_shared_expense_text(
    txn: Transaction,
    persons: list[Person],
    selected_person_ids: list[int],
    index: int | None = None,
    total: int | None = None,
    show_billing_month: bool = False,
) -> str:
    selected_names = [person.name for person in persons if person.id in set(selected_person_ids)]
    lines = [
        _build_review_transaction_text(
            txn,
            index=index,
            total=total,
            show_billing_month=show_billing_month,
        ),
        "",
        "Shared expense mode",
        "Select all people involved, then press Equal split.",
    ]
    if selected_names:
        lines.append(f"Selected: {', '.join(selected_names)}")
    else:
        lines.append("Selected: none")
    return "\n".join(lines)


def _build_assignment_result_text(
    transaction: Transaction,
    label: str,
    draft_bill_ids: list[int] | None = None,
) -> str:
    lines = [
        label,
        "",
        f"Date: {transaction.transaction_date}",
        f"Merchant: {transaction.merchant_name}",
        f"Amount: ${abs(transaction.amount):.2f}",
    ]
    if draft_bill_ids:
        lines.append("")
        lines.append(
            f"Deleted {len(draft_bill_ids)} draft bill(s) so they can be regenerated cleanly."
        )
    return "\n".join(lines)


def _build_shared_assignment_result_text(
    transaction: Transaction,
    draft_bill_ids: list[int] | None = None,
) -> str:
    lines = ["Shared expense saved", ""]
    for person_name, amount in split_summary(transaction):
        lines.append(f"{person_name}: ${amount:.2f}")
    lines.extend(
        [
            "",
            f"Date: {transaction.transaction_date}",
            f"Merchant: {transaction.merchant_name}",
            f"Total: ${abs(transaction.amount):.2f}",
        ]
    )
    if draft_bill_ids:
        lines.append("")
        lines.append(
            f"Deleted {len(draft_bill_ids)} draft bill(s) so they can be regenerated cleanly."
        )
    return "\n".join(lines)


def _get_shared_review_states(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(SHARED_REVIEW_STATES_KEY, {})


def _get_shared_review_selection(
    context: ContextTypes.DEFAULT_TYPE,
    transaction_id: int,
) -> list[int]:
    return list(_get_shared_review_states(context).get(transaction_id, []))


def _set_shared_review_selection(
    context: ContextTypes.DEFAULT_TYPE,
    transaction_id: int,
    person_ids: list[int],
) -> None:
    _get_shared_review_states(context)[transaction_id] = person_ids


def _clear_shared_review_selection(
    context: ContextTypes.DEFAULT_TYPE,
    transaction_id: int,
) -> None:
    _get_shared_review_states(context).pop(transaction_id, None)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_message = (
        "Expense Tracker Bot\n\n"
        "Commands:\n"
        "/review [YYYY-MM] - Review flagged transactions (all months if omitted)\n"
        "/refund [YYYY-MM] - Review orphan refunds\n"
        "/alerts - View card fee alerts\n"
        "/resolved - View resolved alerts\n"
        "/rewards [YYYY-MM] - View rewards summary\n"
        "/bill YYYY-MM [person] - Generate bills\n"
        "/status - Pipeline status\n"
        "/stats - Spending statistics\n"
        "/blacklist - View trigger categories\n"
        "/help - Detailed help\n\n"
        "Import statements from your PC:\n"
        "  cd backend && python import_statements.py 2026-01"
    )
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_message = (
        "Expense Tracker Help\n\n"
        "Workflow:\n"
        "1. Extract PDFs using /extract-statement in Claude Code\n"
        "2. python import_statements.py YYYY-MM (on your PC)\n"
        "3. /review to assign flagged transactions to dad/wife/self\n"
        "4. /bill YYYY-MM to generate monthly bills\n\n"
        "Commands:\n"
        "/review [YYYY-MM] - Review flagged transactions (all months if omitted)\n"
        "/refund [YYYY-MM] - Review orphan/ambiguous refunds\n"
        "/rewards [YYYY-MM] - View cashback and points rewards summary\n"
        "/bill YYYY-MM [name] - Generate bills (optionally filter by person)\n"
        "/status - Show import/review counts per month\n"
        "/stats - Spending totals by person\n"
        "/blacklist - View category trigger keywords\n"
        "/alerts - View pending card fee alerts (late charges, finance charges, etc.)\n"
        "/resolved - View resolved alerts (with option to unresolve)\n"
        "/add_blacklist - Add new trigger category/keywords"
    )
    await update.message.reply_text(help_message)


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload command"""
    message = """
📄 **Upload Credit Card Statement**

PDF auto-parsing has been removed. Please use the /extract-statement Claude Code command to extract transactions from your PDF, then import the JSON data.
    """
    await update.message.reply_text(message)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle PDF document uploads - directs user to use /extract-statement instead"""
    await update.message.reply_text(
        "PDF auto-parsing has been removed.\n\n"
        "Please use the /extract-statement Claude Code command to extract "
        "transactions from your PDF, then import the JSON data."
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button callbacks"""
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split('_')

    if parts[0] == 'assign':
        # Format: assign_{transaction_id}_{person_id}
        transaction_id = int(parts[1])
        person_id = int(parts[2])

        db = SessionLocal()
        try:
            # Get transaction
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                await query.edit_message_text("❌ Transaction not found.")
                return

            # Get person
            person = db.query(Person).filter(Person.id == person_id).first()
            if not person:
                await query.edit_message_text("❌ Person not found.")
                return

            outcome = assign_transaction_to_person(db, transaction, person.id)
            _clear_shared_review_selection(context, transaction_id)

            # Update message
            await query.edit_message_text(
                _build_assignment_result_text(
                    outcome.transaction,
                    f"Assigned to {person.name}",
                    outcome.affected_draft_bill_ids,
                ),
                reply_markup=get_review_result_keyboard(transaction_id),
            )

        finally:
            db.close()

    elif parts[0] == 'undo':
        transaction_id = int(parts[1])

        db = SessionLocal()
        try:
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                await query.edit_message_text("Transaction not found.")
                return

            try:
                outcome = undo_review_assignment(db, transaction)
            except ValueError as e:
                await query.edit_message_text(str(e))
                return

            _clear_shared_review_selection(context, transaction_id)
            await query.edit_message_text(
                _build_assignment_result_text(
                    outcome.transaction,
                    "Moved back to /review",
                    outcome.affected_draft_bill_ids,
                )
            )
        finally:
            db.close()

    elif parts[0] == 'share':
        transaction_id = int(parts[1])

        db = SessionLocal()
        try:
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                await query.edit_message_text("Transaction not found.")
                return

            persons = get_review_persons(db)
            _set_shared_review_selection(context, transaction_id, [])
            await query.edit_message_text(
                _build_shared_expense_text(
                    transaction,
                    persons,
                    [],
                    show_billing_month=bool(transaction.billing_month),
                ),
                reply_markup=get_shared_expense_keyboard(transaction_id, persons, []),
            )
        finally:
            db.close()

    elif parts[0] == 'sharetoggle':
        transaction_id = int(parts[1])
        person_id = int(parts[2])

        db = SessionLocal()
        try:
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                await query.edit_message_text("Transaction not found.")
                return

            persons = get_review_persons(db)
            selected_person_ids = _get_shared_review_selection(context, transaction_id)
            if person_id in selected_person_ids:
                selected_person_ids = [selected for selected in selected_person_ids if selected != person_id]
            else:
                selected_person_ids.append(person_id)
            _set_shared_review_selection(context, transaction_id, selected_person_ids)

            await query.edit_message_text(
                _build_shared_expense_text(
                    transaction,
                    persons,
                    selected_person_ids,
                    show_billing_month=bool(transaction.billing_month),
                ),
                reply_markup=get_shared_expense_keyboard(
                    transaction_id,
                    persons,
                    selected_person_ids,
                ),
            )
        finally:
            db.close()

    elif parts[0] == 'sharesave':
        transaction_id = int(parts[1])

        db = SessionLocal()
        try:
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                await query.edit_message_text("Transaction not found.")
                return

            selected_person_ids = _get_shared_review_selection(context, transaction_id)
            try:
                outcome = assign_transaction_equal_split(db, transaction, selected_person_ids)
            except ValueError as e:
                persons = get_review_persons(db)
                await query.edit_message_text(
                    _build_shared_expense_text(
                        transaction,
                        persons,
                        selected_person_ids,
                        show_billing_month=bool(transaction.billing_month),
                    )
                    + f"\n\n{e}",
                    reply_markup=get_shared_expense_keyboard(
                        transaction_id,
                        persons,
                        selected_person_ids,
                    ),
                )
                return

            _clear_shared_review_selection(context, transaction_id)
            await query.edit_message_text(
                _build_shared_assignment_result_text(
                    outcome.transaction,
                    outcome.affected_draft_bill_ids,
                ),
                reply_markup=get_review_result_keyboard(transaction_id),
            )
        finally:
            db.close()

    elif parts[0] == 'sharecancel':
        transaction_id = int(parts[1])
        db = SessionLocal()
        try:
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                await query.edit_message_text("Transaction not found.")
                return

            persons = get_review_persons(db)
            _clear_shared_review_selection(context, transaction_id)
            await query.edit_message_text(
                _build_review_transaction_text(
                    transaction,
                    show_billing_month=bool(transaction.billing_month),
                ),
                reply_markup=get_review_keyboard(transaction_id, persons),
            )
        finally:
            db.close()

    elif parts[0] == 'add' and parts[1] == 'blacklist':
        # Format: add_blacklist_{transaction_id}
        transaction_id = int(parts[2])

        # Set up conversation state for adding to blacklist
        context.user_data['pending_blacklist_transaction'] = transaction_id

        await query.edit_message_text(
            "📋 **Add to Blacklist**\n\n"
            "Please reply with the category name (e.g., 'flights', 'tours', 'accommodation').\n\n"
            "If the category already exists, I'll add this merchant's keywords to it.\n"
            "Otherwise, I'll create a new category."
        )

    elif parts[0] == 'refmatch':
        # Format: refmatch_{refund_id}_{original_id}
        refund_id = int(parts[1])
        original_id = int(parts[2])

        db = SessionLocal()
        try:
            refund_handler = RefundHandler(db)
            refund = refund_handler.match_refund_manually(refund_id, original_id)
            original = db.query(Transaction).filter(Transaction.id == original_id).first()
            person_name = refund.assigned_person.name if refund.assigned_person else "unknown"

            await query.edit_message_text(
                f"Refund matched\n\n"
                f"Refund: {refund.merchant_name} -${abs(refund.amount):.2f}\n"
                f"Original: {original.transaction_date} ${original.amount:.2f}\n"
                f"Assigned to: {person_name}"
            )
        except ValueError as e:
            await query.edit_message_text(f"Error: {e}")
        finally:
            db.close()

    elif parts[0] == 'refsearch':
        # Format: refsearch_{refund_id}
        refund_id = int(parts[1])

        db = SessionLocal()
        try:
            refund = db.query(Transaction).filter(Transaction.id == refund_id).first()
            if not refund:
                await query.edit_message_text("Transaction not found.")
                return

            refund_handler = RefundHandler(db)
            matches = refund_handler.search_by_amount(refund)

            if not matches:
                await query.edit_message_text(
                    f"No transactions found matching ${abs(refund.amount):.2f}.\n"
                    "Use /refund to try again later."
                )
                return

            # Build keyboard with search results
            keyboard = []
            for m in matches:
                card_info = f"****{m.statement.card_last_4}" if m.statement else ""
                person_name = m.assigned_person.name if m.assigned_person else "unassigned"
                label = f"{m.transaction_date} {card_info} {m.merchant_name} ${m.amount:.2f} ({person_name})"
                if len(label) > 60:
                    label = label[:57] + "..."
                keyboard.append([InlineKeyboardButton(label, callback_data=f"refmatch_{refund_id}_{m.id}")])

            keyboard.append([InlineKeyboardButton("Cancel", callback_data=f"skip_{refund_id}")])

            from telegram import InlineKeyboardMarkup
            await query.edit_message_text(
                f"Search results for ${abs(refund.amount):.2f}:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        finally:
            db.close()

    elif parts[0] == 'refassign':
        # Format: refassign_{refund_id} — show person buttons for direct assignment
        refund_id = int(parts[1])

        db = SessionLocal()
        try:
            persons = get_review_persons(db)
            keyboard = get_refund_person_keyboard(refund_id, persons)
            await query.edit_message_reply_markup(reply_markup=keyboard)
        finally:
            db.close()

    elif parts[0] == 'resolve':
        # Format: resolve_{transaction_id}
        transaction_id = int(parts[1])

        db = SessionLocal()
        try:
            txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not txn:
                await query.edit_message_text("Transaction not found.")
                return

            txn.alert_status = 'resolved'
            txn.resolved_method = 'manual'
            db.commit()

            await query.edit_message_text(
                f"Resolved: {txn.merchant_name} ${abs(txn.amount):.2f}\n"
                f"Date: {txn.transaction_date}"
            )
        finally:
            db.close()

    elif parts[0] == 'unresolved':
        # Format: unresolved_{transaction_id}
        transaction_id = int(parts[1])

        db = SessionLocal()
        try:
            txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not txn:
                await query.edit_message_text("Transaction not found.")
                return

            txn.alert_status = 'unresolved'
            db.commit()

            await query.edit_message_text(
                f"Marked unresolved: {txn.merchant_name} ${abs(txn.amount):.2f}\n"
                f"Date: {txn.transaction_date}\n"
                "This will continue to show in /alerts."
            )
        finally:
            db.close()

    elif parts[0] == 'unresolve':
        # Format: unresolve_{transaction_id}
        transaction_id = int(parts[1])

        db = SessionLocal()
        try:
            txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not txn:
                await query.edit_message_text("Transaction not found.")
                return

            txn.alert_status = 'unresolved'
            txn.resolved_method = None
            txn.resolved_by_transaction_id = None
            db.commit()

            await query.edit_message_text(
                f"Unresolved: {txn.merchant_name} ${abs(txn.amount):.2f}\n"
                f"Date: {txn.transaction_date}\n"
                "Moved back to /alerts."
            )
        finally:
            db.close()

    elif parts[0] == 'skip':
        # Format: skip_{transaction_id}
        transaction_id = int(parts[1])

        await query.edit_message_text(
            "Skipped. You can review this transaction later."
        )

    elif parts[0] == 'bill':
        # Format: bill_{action}_{bill_id}
        action = parts[1]
        bill_id = int(parts[2])

        db = SessionLocal()
        try:
            generator = BillGenerator(db)

            if action == 'finalize':
                bill = generator.finalize_bill(bill_id)
            elif action == 'pay':
                bill = generator.mark_bill_paid(bill_id)
            elif action == 'unpay':
                bill = generator.mark_bill_unpaid(bill_id)
            else:
                await query.edit_message_text("Unknown bill action.")
                return

            text, keyboard = _build_bill_response(db, generator, bill)
            await query.edit_message_text(text, reply_markup=keyboard)
        except ValueError as e:
            await query.edit_message_text(f"Bill action failed: {e}")
        finally:
            db.close()


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    db = SessionLocal()
    try:
        # Get all persons
        persons = db.query(Person).all()

        if not persons:
            await update.message.reply_text(
                "❌ No family members configured yet. Please set up persons first."
            )
            return

        stats_message = "📊 **Spending Statistics**\n\n"

        for person in persons:
            # Get total spending
            total = sum(
                txn.amount for txn in person.transactions
                if txn.amount > 0  # Exclude refunds
            )

            # Get transaction count
            count = len([txn for txn in person.transactions if txn.amount > 0])

            stats_message += f"**{person.name}** ({person.relationship_type})\n"
            stats_message += f"• Total: ${total:.2f}\n"
            stats_message += f"• Transactions: {count}\n\n"

        await update.message.reply_text(stats_message)

    finally:
        db.close()


async def blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /blacklist command - view all blacklist categories"""
    db = SessionLocal()
    try:
        categories = db.query(BlacklistCategory).filter(BlacklistCategory.is_active == True).all()

        if not categories:
            await update.message.reply_text(
                "❌ No blacklist categories configured yet."
            )
            return

        message = "📋 **Blacklist Categories**\n\n"
        message += "These categories trigger manual review for 'self' transactions:\n\n"

        for category in categories:
            keywords_str = ", ".join(category.keywords[:5])
            if len(category.keywords) > 5:
                keywords_str += f" ... (+{len(category.keywords) - 5} more)"

            message += f"**{category.name}**\n"
            message += f"Keywords: {keywords_str}\n\n"

        message += "\nUse /add_blacklist to add new categories or keywords."

        await update.message.reply_text(message)

    finally:
        db.close()


async def add_blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /add_blacklist command - start conversation to add blacklist category"""
    context.user_data['adding_blacklist'] = True

    await update.message.reply_text(
        "📋 **Add to Blacklist**\n\n"
        "Enter the category name (e.g., 'flights', 'tours', 'accommodation').\n\n"
        "If the category already exists, I'll ask you to add keywords to it.\n"
        "Otherwise, I'll create a new category."
    )


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /import command - import JSON statements for a billing month.

    Usage: /import YYYY-MM  (e.g. /import 2026-03)
    """
    # Parse billing month from args
    if not context.args:
        await update.message.reply_text(
            "Usage: /import YYYY-MM\n\nExample: /import 2026-03"
        )
        return

    month_str = context.args[0]
    match = re.match(r'^(\d{4})-(\d{2})$', month_str)
    if not match:
        await update.message.reply_text(
            "Invalid format. Use YYYY-MM (e.g. 2026-03)"
        )
        return

    year, month = int(match.group(1)), int(match.group(2))
    if month < 1 or month > 12:
        await update.message.reply_text("Month must be between 01 and 12.")
        return

    await update.message.reply_text(f"Importing statements for {month_str}...")

    db = SessionLocal()
    try:
        importer = StatementImporter(db)
        result = importer.import_month(year, month)

        # Build summary message
        lines = [f"Import complete for {result.billing_month}\n"]
        lines.append(f"Files imported: {result.files_imported}")
        lines.append(f"Files skipped: {result.files_skipped}")
        if result.files_errored:
            lines.append(f"Files errored: {result.files_errored}")
        lines.append(f"Transactions: {result.total_transactions}")
        lines.append(f"Flagged for review: {result.total_flagged}")
        lines.append(f"Refunds auto-matched: {result.total_refunds_matched}")

        if result.files_errored:
            lines.append("\nErrors:")
            for fr in result.file_results:
                if fr.error:
                    lines.append(f"  {fr.filename}: {fr.error}")

        if result.total_flagged > 0:
            lines.append(f"\nUse /review {month_str} to review flagged transactions.")

        await update.message.reply_text("\n".join(lines))

    except Exception as e:
        logger.exception("Import failed for %s", month_str)
        await update.message.reply_text(f"Import failed: {e}")
    finally:
        db.close()


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - show pipeline status summary."""
    db = SessionLocal()
    try:
        # Get recent billing months with data
        months = (
            db.query(Statement.billing_month)
            .filter(Statement.billing_month.isnot(None))
            .distinct()
            .order_by(Statement.billing_month.desc())
            .limit(6)
            .all()
        )

        if not months:
            await update.message.reply_text("No imported data yet. Use /import YYYY-MM to start.")
            return

        lines = ["Pipeline Status\n"]
        for (billing_month,) in months:
            total = db.query(Transaction).filter(
                Transaction.billing_month == billing_month
            ).count()
            pending = db.query(Transaction).filter(
                Transaction.billing_month == billing_month,
                Transaction.needs_review == True,
            ).count()
            lines.append(f"{billing_month}: {total} transactions ({pending} pending review)")

        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /review command - show pending review queue.

    Usage: /review [YYYY-MM]
    Without a month, shows all pending reviews across all months.
    """
    db = SessionLocal()
    try:
        filters = [Transaction.needs_review == True]

        if context.args:
            billing_month = context.args[0]
            filters.append(Transaction.billing_month == billing_month)
        else:
            billing_month = None

        pending = (
            db.query(Transaction)
            .filter(*filters)
            .order_by(Transaction.billing_month.desc(), Transaction.transaction_date, Transaction.id)
            .all()
        )

        if not pending:
            if billing_month:
                await update.message.reply_text(f"No pending reviews for {billing_month}.")
            else:
                await update.message.reply_text("No transactions pending review.")
            return

        persons = get_review_persons(db)

        if billing_month:
            header = f"Review queue for {billing_month}: {len(pending)} transactions"
        else:
            months = sorted({txn.billing_month for txn in pending}, reverse=True)
            header = (
                f"All pending reviews: {len(pending)} transactions across "
                f"{len(months)} month(s)\nMonths: {', '.join(months)}"
            )

        await update.message.reply_text(header)

        # Send each transaction as a separate message with inline keyboard
        for i, txn in enumerate(pending, 1):
            text = _build_review_transaction_text(
                txn,
                index=i,
                total=len(pending),
                show_billing_month=not billing_month,
            )

            # Use refund keyboard for refund transactions, regular for others
            if txn.is_refund and txn.assignment_method in ('refund_ambiguous', 'refund_orphan'):
                refund_handler = RefundHandler(db)
                candidates = refund_handler.get_broad_candidates(txn)
                keyboard = get_refund_review_keyboard(txn.id, candidates, persons)
            else:
                keyboard = get_review_keyboard(txn.id, persons)

            await update.message.reply_text(text, reply_markup=keyboard)

    finally:
        db.close()


async def refunds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /refund(s) command - show orphan/ambiguous refunds.

    Usage: /refund [YYYY-MM]
    Without a month, shows all pending orphan/ambiguous refunds.
    """
    db = SessionLocal()
    try:
        filters = [
            Transaction.needs_review == True,
            Transaction.assignment_method.in_(['refund_orphan', 'refund_ambiguous']),
        ]

        if context.args:
            billing_month = context.args[0]
            filters.append(Transaction.billing_month == billing_month)
        else:
            billing_month = None

        pending = (
            db.query(Transaction)
            .filter(*filters)
            .order_by(Transaction.billing_month.desc(), Transaction.transaction_date, Transaction.id)
            .all()
        )

        if not pending:
            if billing_month:
                await update.message.reply_text(f"No orphan refunds for {billing_month}.")
            else:
                await update.message.reply_text("No orphan refunds pending review.")
            return

        if billing_month:
            header = f"Orphan refunds for {billing_month}: {len(pending)} transactions"
        else:
            months = sorted({txn.billing_month for txn in pending}, reverse=True)
            header = (
                f"All pending orphan refunds: {len(pending)} transactions across "
                f"{len(months)} month(s)\nMonths: {', '.join(months)}"
            )

        await update.message.reply_text(header)

        for i, txn in enumerate(pending, 1):
            card_info = ""
            card_owner = None
            if txn.statement:
                card_info = f"Card: {txn.statement.bank_name or ''} ****{txn.statement.card_last_4}"
                card_owner = get_card_owner_name(db, txn.statement)

            amount_str = f"-${abs(txn.amount):.2f}"

            lines = [
                f"Orphan refund {i}/{len(pending)}:",
                f"{txn.merchant_name} {amount_str}",
            ]
            lines.append(f"Billing month: {txn.billing_month}")
            if card_info:
                lines.append(card_info)
            if card_owner:
                lines.append(f"Card owner: {card_owner}")
            lines.append(f"Date: {txn.transaction_date}")
            if txn.assignment_method:
                lines.append(f"Status: {txn.assignment_method}")

            # Use broad candidates for better matching
            refund_handler = RefundHandler(db)
            candidates = refund_handler.get_broad_candidates(txn)

            if candidates:
                lines.append(f"\nPossible matches ({len(candidates)}):")

            text = "\n".join(lines)
            keyboard = get_refund_review_keyboard(txn.id, candidates, [])
            await update.message.reply_text(text, reply_markup=keyboard)

    finally:
        db.close()


async def bill_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bill command - generate/preview bill for a billing month.

    Usage: /bill YYYY-MM [person_name]
    """
    if not context.args:
        await update.message.reply_text("Usage: /bill YYYY-MM [person_name]")
        return

    billing_month = context.args[0]
    person_filter = context.args[1] if len(context.args) > 1 else None

    db = SessionLocal()
    try:
        generator = BillGenerator(db)

        # Get persons to bill (non-self)
        if person_filter:
            persons = _find_persons_for_bill_filter(db, person_filter)
            logger.info(
                "Bill command filter '%s' matched persons=%s",
                person_filter,
                [p.name for p in persons],
            )
            if not persons:
                await update.message.reply_text(f"No person found matching '{person_filter}'.")
                return
        else:
            persons = db.query(Person).filter(
                Person.is_auto_created == False
            ).order_by(Person.name).all()

        if not persons:
            await update.message.reply_text("No family members configured.")
            return

        for person in persons:
            bill = generator.generate_bill(person.id, billing_month)
            if not bill:
                await update.message.reply_text(f"No billable items for {person.name} in {billing_month}.")
                continue

            text, keyboard = _build_bill_response(db, generator, bill)
            logger.info(
                "Sending bill message: bill_id=%s person=%s keyboard=%s",
                bill.id,
                person.name,
                keyboard.to_dict() if keyboard else None,
            )
            await update.message.reply_text(text, reply_markup=keyboard)

    except Exception as e:
        logger.exception("Bill generation failed")
        await update.message.reply_text(f"Bill generation failed: {e}")
    finally:
        db.close()


async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts command - show pending + unresolved card fee alerts across all months."""
    db = SessionLocal()
    try:
        from sqlalchemy import func as sqlfunc

        # Get all pending/unresolved alerts (exclude GST child lines)
        alerts = (
            db.query(Transaction)
            .join(Statement)
            .filter(
                Transaction.alert_status.in_(['pending', 'unresolved']),
                Transaction.parent_transaction_id.is_(None),
            )
            .order_by(Transaction.transaction_date.desc())
            .all()
        )

        if not alerts:
            await update.message.reply_text("No pending alerts.")
            return

        await update.message.reply_text(f"Card fee alerts: {len(alerts)} pending\n")

        for i, txn in enumerate(alerts, 1):
            card_info = ""
            if txn.statement:
                card_info = f"{txn.statement.bank_name or ''} ****{txn.statement.card_last_4}"

            # Calculate combined total (fee + GST children)
            gst_children = (
                db.query(Transaction)
                .filter(Transaction.parent_transaction_id == txn.id)
                .all()
            )
            gst_total = sum(abs(c.amount) for c in gst_children)
            combined_total = abs(txn.amount) + gst_total

            status_badge = "NEW" if txn.alert_status == 'pending' else "UNRESOLVED"
            amount_prefix = "-" if txn.is_refund else ""

            lines = [f"[{status_badge}] {txn.merchant_name}"]
            lines.append(f"Amount: {amount_prefix}${combined_total:.2f}")
            if gst_total > 0:
                lines.append(f"  (Fee: ${abs(txn.amount):.2f} + GST: ${gst_total:.2f})")
            if card_info:
                lines.append(f"Card: {card_info}")
            lines.append(f"Date: {txn.transaction_date}")
            lines.append(f"Month: {txn.billing_month or 'N/A'}")

            text = "\n".join(lines)
            keyboard = get_alert_keyboard(txn.id)
            await update.message.reply_text(text, reply_markup=keyboard)

    finally:
        db.close()


async def resolved_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resolved command - show resolved alerts with option to unresolve."""
    db = SessionLocal()
    try:
        # Get resolved alerts (exclude GST child lines), most recent 20
        resolved = (
            db.query(Transaction)
            .join(Statement)
            .filter(
                Transaction.alert_status == 'resolved',
                Transaction.parent_transaction_id.is_(None),
            )
            .order_by(Transaction.transaction_date.desc())
            .limit(20)
            .all()
        )

        if not resolved:
            await update.message.reply_text("No resolved alerts.")
            return

        await update.message.reply_text(f"Resolved alerts (most recent 20):\n")

        for txn in resolved:
            card_info = ""
            if txn.statement:
                card_info = f"{txn.statement.bank_name or ''} ****{txn.statement.card_last_4}"

            # Combined total
            gst_children = (
                db.query(Transaction)
                .filter(Transaction.parent_transaction_id == txn.id)
                .all()
            )
            gst_total = sum(abs(c.amount) for c in gst_children)
            combined_total = abs(txn.amount) + gst_total

            method_badge = "AUTO" if txn.resolved_method == 'auto' else "MANUAL"
            amount_prefix = "-" if txn.is_refund else ""

            lines = [f"[{method_badge}] {txn.merchant_name}"]
            lines.append(f"Amount: {amount_prefix}${combined_total:.2f}")
            if card_info:
                lines.append(f"Card: {card_info}")
            lines.append(f"Date: {txn.transaction_date}")

            # Show linked reversal info for auto-resolved
            if txn.resolved_by_transaction_id:
                reversal = db.query(Transaction).filter(
                    Transaction.id == txn.resolved_by_transaction_id
                ).first()
                if reversal:
                    lines.append(f"Reversed by: {reversal.merchant_name} -${abs(reversal.amount):.2f} ({reversal.transaction_date})")

            text = "\n".join(lines)
            keyboard = get_resolved_keyboard(txn.id)
            await update.message.reply_text(text, reply_markup=keyboard)

    finally:
        db.close()


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (for blacklist category input)"""
    # Check if user is adding a blacklist category
    if context.user_data.get('adding_blacklist'):
        category_name = update.message.text.strip().lower()

        db = SessionLocal()
        try:
            # Check if category exists
            existing_category = db.query(BlacklistCategory).filter(
                BlacklistCategory.name == category_name
            ).first()

            if existing_category:
                # Category exists, ask for keywords to add
                context.user_data['blacklist_category_name'] = category_name
                context.user_data['adding_blacklist'] = False
                context.user_data['adding_blacklist_keywords'] = True

                await update.message.reply_text(
                    f"Category '{category_name}' already exists.\n\n"
                    f"Current keywords: {', '.join(existing_category.keywords)}\n\n"
                    "Enter new keywords to add (comma-separated):"
                )
            else:
                # New category, ask for keywords
                context.user_data['blacklist_category_name'] = category_name
                context.user_data['adding_blacklist'] = False
                context.user_data['adding_blacklist_keywords'] = True

                await update.message.reply_text(
                    f"Creating new category: '{category_name}'\n\n"
                    "Enter keywords for this category (comma-separated):"
                )

        finally:
            db.close()

    elif context.user_data.get('adding_blacklist_keywords'):
        # User is providing keywords
        category_name = context.user_data.get('blacklist_category_name')
        keywords_text = update.message.text.strip()
        keywords = [k.strip() for k in keywords_text.split(',') if k.strip()]

        if not keywords:
            await update.message.reply_text("❌ No keywords provided. Please try again.")
            return

        db = SessionLocal()
        try:
            from app.services.blacklist_matcher import BlacklistMatcher
            matcher = BlacklistMatcher(db)

            # Check if category exists
            existing_category = db.query(BlacklistCategory).filter(
                BlacklistCategory.name == category_name
            ).first()

            if existing_category:
                # Add keywords to existing category
                category = matcher.add_keywords_to_category(category_name, keywords)
                await update.message.reply_text(
                    f"✅ Added {len(keywords)} keyword(s) to category '{category_name}'.\n\n"
                    f"Total keywords: {len(category.keywords)}"
                )
            else:
                # Create new category
                category = matcher.add_category(category_name, keywords)
                await update.message.reply_text(
                    f"✅ Created new category '{category_name}' with {len(keywords)} keyword(s)."
                )

            # Clear state
            context.user_data['adding_blacklist_keywords'] = False
            context.user_data['blacklist_category_name'] = None

        finally:
            db.close()

    elif context.user_data.get('pending_blacklist_transaction'):
        # User is adding a transaction's merchant to blacklist
        category_name = update.message.text.strip().lower()
        transaction_id = context.user_data['pending_blacklist_transaction']

        db = SessionLocal()
        try:
            # Get the transaction
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                await update.message.reply_text("❌ Transaction not found.")
                return

            # Extract merchant name as keyword
            merchant_keyword = transaction.merchant_name.lower().strip()

            from app.services.blacklist_matcher import BlacklistMatcher
            matcher = BlacklistMatcher(db)

            # Check if category exists
            existing_category = db.query(BlacklistCategory).filter(
                BlacklistCategory.name == category_name
            ).first()

            if existing_category:
                # Add merchant to existing category
                category = matcher.add_keywords_to_category(category_name, [merchant_keyword])
                await update.message.reply_text(
                    f"✅ Added '{merchant_keyword}' to category '{category_name}'.\n\n"
                    f"This merchant will now trigger manual review for 'self' transactions."
                )
            else:
                # Create new category with this merchant
                category = matcher.add_category(category_name, [merchant_keyword])
                await update.message.reply_text(
                    f"✅ Created new category '{category_name}' with keyword '{merchant_keyword}'.\n\n"
                    f"This merchant will now trigger manual review for 'self' transactions."
                )

            # Clear state
            context.user_data['pending_blacklist_transaction'] = None

        finally:
            db.close()


async def rewards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /rewards command - show cashback and points summary.

    Usage: /rewards [YYYY-MM]
    If no month given: show cumulative totals per card across all months.
    """
    db = SessionLocal()
    try:
        billing_month = context.args[0] if context.args else None

        if billing_month:
            rewards = (
                db.query(CardReward)
                .filter(CardReward.billing_month == billing_month)
                .order_by(CardReward.reward_type, CardReward.bank_name, CardReward.card_last_4)
                .all()
            )
            if not rewards:
                await update.message.reply_text(f"No rewards recorded for {billing_month}.")
                return
            title = f"Rewards Summary — {billing_month}"
        else:
            # Latest 12 months
            rewards = (
                db.query(CardReward)
                .order_by(CardReward.billing_month.desc(), CardReward.reward_type, CardReward.bank_name)
                .all()
            )
            if not rewards:
                await update.message.reply_text("No rewards recorded yet.")
                return
            title = "Rewards Summary — All Time"

        lines = [title, ""]

        # Group by reward_type
        cashback = [r for r in rewards if r.reward_type == "cashback"]
        non_cashback = [r for r in rewards if r.reward_type != "cashback"]

        # --- Cashback section ---
        if cashback:
            lines.append("Cashback:")
            total_cashback = 0.0
            for r in cashback:
                card_label = f"{r.bank_name or 'Unknown'} ****{r.card_last_4 or '????'}"
                person_name = r.person.name if r.person else "unknown"
                month_label = f" ({r.billing_month})" if not billing_month else ""
                lines.append(f"  {card_label}{month_label}   ${r.earned_this_period:.2f}")
                total_cashback += r.earned_this_period
            if len(cashback) > 1:
                lines.append(f"  Total SGD cashback:   ${total_cashback:.2f}")
            lines.append("")

        # --- Points / miles / uni_dollars sections ---
        seen_types = {}
        for r in non_cashback:
            key = r.reward_type
            seen_types.setdefault(key, []).append(r)

        three_months_from_now = date.today() + timedelta(days=90)

        for reward_type, items in seen_types.items():
            type_label = reward_type.replace("_", " ").title()
            for r in items:
                card_label = f"{r.bank_name or 'Unknown'} ****{r.card_last_4 or '????'}"
                lines.append(f"{type_label} — {card_label}:")

                unit = "pts" if reward_type in ("points", "uni_dollars") else reward_type
                lines.append(f"  Earned this period:   {r.earned_this_period:,.0f} {unit}")

                if r.balance is not None:
                    lines.append(f"  Balance:              {r.balance:,.0f} {unit}")

                if r.expiry_date:
                    expiry_str = r.expiry_date.strftime("%d %b %Y")
                    expiry_warn = " ⚠️ expires soon" if r.expiry_date <= three_months_from_now else ""
                    lines.append(f"  Expires: {expiry_str}{expiry_warn}")
                else:
                    lines.append("  No expiry shown")
                lines.append("")

        await update.message.reply_text("\n".join(lines))

    finally:
        db.close()
