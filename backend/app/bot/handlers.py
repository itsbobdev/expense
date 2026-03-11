from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Person, Statement, Transaction
from app.parsers import ParserFactory
from app.services.categorizer import TransactionCategorizer
from app.bot.keyboards import get_review_keyboard
from app.config import settings
from datetime import datetime
import os


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_message = """
👋 Welcome to Expense Tracker Bot!

I help you track expenses from credit card statements and generate bills for your family.

**Available Commands:**
/start - Show this welcome message
/help - Get help with using the bot
/upload - Upload a credit card statement PDF
/stats - View spending statistics
/bill [month] [person] - Generate a bill

**How to Use:**
1. Upload your credit card statement PDF using /upload
2. I'll automatically categorize transactions
3. Review any uncertain transactions
4. Generate bills with /bill command

Let's get started! Upload your first statement with /upload
    """
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_message = """
📖 **Expense Tracker Bot Help**

**Commands:**
• /start - Welcome message and introduction
• /help - Show this help message
• /upload - Upload a credit card statement PDF
• /stats - View spending statistics by person
• /bill <month> <person> - Generate a bill
  Example: /bill march parent

**Uploading Statements:**
1. Send /upload command
2. Upload your PDF statement when prompted
3. The bot will process and categorize transactions
4. Review any uncertain transactions using the buttons

**Transaction Review:**
When the bot is uncertain about who should pay for a transaction, you'll get a review prompt with buttons:
• 👨 Parent - Assign to parent
• 👫 Spouse - Assign to spouse
• 👤 Self - Assign to yourself
• ❌ Skip - Skip for now

**Tips:**
• The bot learns from your assignments over time
• Refunds are automatically matched to original transactions
• You can generate bills for any date range

Need more help? Contact support or check the documentation.
    """
    await update.message.reply_text(help_message)


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload command"""
    message = """
📄 **Upload Credit Card Statement**

Please send me your credit card statement PDF file.

**Supported Banks:**
• DBS/POSB ✅
• Maybank ✅
• UOB ✅
• OCBC (coming soon)
• Citibank (coming soon)

Simply attach the PDF file to your next message and I'll process it automatically.
    """
    await update.message.reply_text(message)
    # Set state to waiting for file
    context.user_data['awaiting_upload'] = True


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle PDF document uploads"""
    # Check if we're expecting an upload
    if not context.user_data.get('awaiting_upload'):
        await update.message.reply_text(
            "Please use /upload command first before sending a file."
        )
        return

    # Get the document
    document = update.message.document
    if not document.file_name.endswith('.pdf'):
        await update.message.reply_text(
            "❌ Please send a PDF file. Other file formats are not supported yet."
        )
        return

    # Send processing message
    processing_msg = await update.message.reply_text(
        "📄 Processing statement... This may take a moment."
    )

    try:
        # Download the file
        file = await context.bot.get_file(document.file_id)
        file_path = os.path.join(settings.upload_dir, document.file_name)
        await file.download_to_drive(file_path)

        # Auto-detect bank and parse the PDF
        parsed_data = ParserFactory.parse(file_path)

        if not parsed_data:
            # Could not detect bank or parse statement
            bank = ParserFactory.detect_bank(file_path)
            if not bank:
                await processing_msg.edit_text(
                    "❌ Could not detect bank from the statement.\n\n"
                    "**Supported banks:**\n"
                    "• DBS/POSB\n"
                    "• Maybank\n"
                    "• UOB\n\n"
                    "Please make sure you're uploading a valid credit card statement from one of these banks."
                )
            else:
                await processing_msg.edit_text(
                    f"❌ Detected {bank.upper()} statement, but failed to parse it.\n\n"
                    "This might be due to an unexpected format. "
                    "Please report this issue or try a different statement."
                )
            return

        if not parsed_data.get('transactions'):
            await processing_msg.edit_text(
                "❌ No transactions found in the statement. Please check the file and try again."
            )
            return

        # Create database session
        db = SessionLocal()
        try:
            # Create statement record
            statement = Statement(
                filename=document.file_name,
                card_last_4=parsed_data['card_last_4'] or 'XXXX',
                statement_date=parsed_data['statement_date'] or datetime.now().date(),
                status='processing',
                raw_file_path=file_path,
            )
            db.add(statement)
            db.commit()
            db.refresh(statement)

            # Create transaction records and categorize
            categorizer = TransactionCategorizer(db)
            transactions_needing_review = []

            for txn_data in parsed_data['transactions']:
                transaction = Transaction(
                    statement_id=statement.id,
                    transaction_date=txn_data['transaction_date'],
                    merchant_name=txn_data['merchant_name'],
                    amount=txn_data['amount'],
                    is_refund=txn_data.get('is_refund', False),
                )
                db.add(transaction)
                db.commit()
                db.refresh(transaction)

                # Categorize transaction
                result = categorizer.categorize(transaction)

                transaction.assigned_to_person_id = result.person_id
                transaction.assignment_confidence = result.confidence
                transaction.assignment_method = result.method
                transaction.needs_review = result.needs_review

                if result.needs_review:
                    transactions_needing_review.append(transaction)

                db.commit()

            # Update statement status
            statement.status = 'processed'
            statement.processed_at = datetime.utcnow()
            db.commit()

            # Send summary
            total_txns = len(parsed_data['transactions'])
            needs_review = len(transactions_needing_review)
            auto_assigned = total_txns - needs_review

            summary = f"""
✅ **Statement Processed Successfully!**

📊 **Summary:**
• Total transactions: {total_txns}
• Auto-assigned: {auto_assigned}
• Need review: {needs_review}

Card: •••• {statement.card_last_4}
Period: {statement.statement_date}
            """
            await processing_msg.edit_text(summary)

            # Send review prompts for uncertain transactions
            if transactions_needing_review:
                await update.message.reply_text(
                    f"🤔 {needs_review} transaction(s) need your review. "
                    "I'll send them one by one..."
                )

                for txn in transactions_needing_review[:5]:  # Limit to 5 at a time
                    review_message = f"""
🤔 **Transaction Review**

📅 Date: {txn.transaction_date}
🏪 Merchant: {txn.merchant_name}
💰 Amount: ${abs(txn.amount):.2f} {'(Refund)' if txn.is_refund else ''}

Who should pay for this?
                    """
                    await update.message.reply_text(
                        review_message,
                        reply_markup=get_review_keyboard(txn.id)
                    )

                if len(transactions_needing_review) > 5:
                    await update.message.reply_text(
                        f"(Showing 5 of {needs_review} transactions. "
                        "Assign these first, then use /review to see more)"
                    )

        finally:
            db.close()

    except Exception as e:
        await processing_msg.edit_text(
            f"❌ Error processing statement: {str(e)}\n\n"
            "Please try again or contact support if the issue persists."
        )

    finally:
        # Clear the upload state
        context.user_data['awaiting_upload'] = False


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button callbacks"""
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split('_')

    if parts[0] == 'assign':
        # Format: assign_{transaction_id}_{person_type}
        transaction_id = int(parts[1])
        person_type = parts[2]

        db = SessionLocal()
        try:
            # Get transaction
            transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                await query.edit_message_text("❌ Transaction not found.")
                return

            # Get person by relationship type
            person = db.query(Person).filter(Person.relationship_type == person_type).first()
            if not person:
                await query.edit_message_text(
                    f"❌ No {person_type} configured. Please set up family members first."
                )
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
                f"✅ Assigned to **{person.name}** ({person_type})\n\n"
                f"📅 {transaction.transaction_date}\n"
                f"🏪 {transaction.merchant_name}\n"
                f"💰 ${abs(transaction.amount):.2f}"
            )

        finally:
            db.close()

    elif parts[0] == 'skip':
        # Format: skip_{transaction_id}
        transaction_id = int(parts[1])

        await query.edit_message_text(
            "⏭️ Skipped. You can review this transaction later."
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
