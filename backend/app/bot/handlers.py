import re
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Person, Statement, Transaction, BlacklistCategory
from app.services.categorizer import TransactionCategorizer
from app.services.refund_handler import RefundHandler
from app.services.importer import StatementImporter
from app.bot.keyboards import (
    get_review_keyboard, get_refund_review_keyboard, get_refund_person_keyboard,
    get_alert_keyboard, get_resolved_keyboard,
)
from app.config import settings

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_message = (
        "Expense Tracker Bot\n\n"
        "Commands:\n"
        "/review [YYYY-MM] - Review flagged transactions\n"
        "/refunds [YYYY-MM] - Review orphan refunds\n"
        "/alerts - View card fee alerts\n"
        "/resolved - View resolved alerts\n"
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
        "/review [YYYY-MM] - Review flagged transactions (defaults to latest)\n"
        "/refunds [YYYY-MM] - Review orphan/ambiguous refunds\n"
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

            # Assign transaction
            transaction.assigned_to_person_id = person.id
            transaction.assignment_confidence = 1.0
            transaction.assignment_method = 'manual'
            transaction.needs_review = False
            transaction.reviewed_at = datetime.utcnow()
            db.commit()

            # Update message
            await query.edit_message_text(
                f"✅ Assigned to **{person.name}**\n\n"
                f"📅 {transaction.transaction_date}\n"
                f"🏪 {transaction.merchant_name}\n"
                f"💰 ${abs(transaction.amount):.2f}"
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
                    "Use /refunds to try again later."
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
            persons = (
                db.query(Person)
                .filter(Person.is_auto_created == False)
                .order_by(Person.name)
                .all()
            )
            self_person = db.query(Person).filter(Person.relationship_type == "self").first()
            if self_person:
                persons.append(self_person)

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

    Usage: /review [YYYY-MM]  (defaults to latest month with pending reviews)
    """
    db = SessionLocal()
    try:
        # Determine billing month
        if context.args:
            billing_month = context.args[0]
        else:
            # Find latest month with pending reviews
            row = (
                db.query(Transaction.billing_month)
                .filter(Transaction.needs_review == True)
                .order_by(Transaction.billing_month.desc())
                .first()
            )
            if not row:
                await update.message.reply_text("No transactions pending review.")
                return
            billing_month = row[0]

        # Get pending transactions for this month
        pending = (
            db.query(Transaction)
            .filter(
                Transaction.billing_month == billing_month,
                Transaction.needs_review == True,
            )
            .order_by(Transaction.transaction_date)
            .all()
        )

        if not pending:
            await update.message.reply_text(f"No pending reviews for {billing_month}.")
            return

        # Get all non-self persons for assignment buttons
        persons = (
            db.query(Person)
            .filter(Person.is_auto_created == False)
            .order_by(Person.name)
            .all()
        )
        # Also include self person
        self_person = db.query(Person).filter(Person.relationship_type == "self").first()
        if self_person:
            persons.append(self_person)

        await update.message.reply_text(
            f"Review queue for {billing_month}: {len(pending)} transactions\n"
        )

        # Send each transaction as a separate message with inline keyboard
        for i, txn in enumerate(pending, 1):
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

            lines = [f"{i}/{len(pending)}: {txn.merchant_name} {amount_str}"]
            if card_info:
                lines.append(card_info)
            if category_info:
                lines.append(category_info)
            if method_info:
                lines.append(method_info)
            lines.append(f"Date: {txn.transaction_date}")

            text = "\n".join(lines)

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
    """Handle /refunds command - show orphan/ambiguous refunds.

    Usage: /refunds [YYYY-MM]  (defaults to latest month with orphan refunds)
    """
    db = SessionLocal()
    try:
        # Determine billing month
        if context.args:
            billing_month = context.args[0]
        else:
            row = (
                db.query(Transaction.billing_month)
                .filter(
                    Transaction.needs_review == True,
                    Transaction.assignment_method.in_(['refund_orphan', 'refund_ambiguous']),
                )
                .order_by(Transaction.billing_month.desc())
                .first()
            )
            if not row:
                await update.message.reply_text("No orphan refunds pending review.")
                return
            billing_month = row[0]

        # Get orphan/ambiguous refunds for this month
        pending = (
            db.query(Transaction)
            .filter(
                Transaction.billing_month == billing_month,
                Transaction.needs_review == True,
                Transaction.assignment_method.in_(['refund_orphan', 'refund_ambiguous']),
            )
            .order_by(Transaction.transaction_date)
            .all()
        )

        if not pending:
            await update.message.reply_text(f"No orphan refunds for {billing_month}.")
            return

        await update.message.reply_text(
            f"Orphan refunds for {billing_month}: {len(pending)} transactions\n"
        )

        for i, txn in enumerate(pending, 1):
            card_info = ""
            if txn.statement:
                card_info = f"Card: {txn.statement.bank_name or ''} ****{txn.statement.card_last_4}"

            amount_str = f"-${abs(txn.amount):.2f}"

            lines = [
                f"Orphan refund {i}/{len(pending)}:",
                f"{txn.merchant_name} {amount_str}",
            ]
            if card_info:
                lines.append(card_info)
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
        from app.services.bill_generator import BillGenerator
        generator = BillGenerator(db)

        # Get persons to bill (non-self)
        if person_filter:
            persons = db.query(Person).filter(
                Person.name.ilike(f"%{person_filter}%")
            ).all()
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

            text = generator.format_bill_message(bill.id)
            # Check for unreviewed transactions
            pending = db.query(Transaction).filter(
                Transaction.billing_month == billing_month,
                Transaction.assigned_to_person_id == person.id,
                Transaction.needs_review == True,
            ).count()

            if pending > 0:
                text += f"\n\nWarning: {pending} transaction(s) still pending review."

            # Check for unmatched orphan refunds in this billing month
            orphan_refunds = db.query(Transaction).filter(
                Transaction.billing_month == billing_month,
                Transaction.needs_review == True,
                Transaction.assignment_method.in_(['refund_orphan', 'refund_ambiguous']),
            ).count()

            if orphan_refunds > 0:
                text += (
                    f"\n\nWarning: {orphan_refunds} orphan refund(s) in {billing_month} "
                    f"not yet matched. Run /refunds {billing_month} to resolve."
                )

            await update.message.reply_text(text)

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
