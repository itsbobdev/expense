from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Person, Statement, Transaction, BlacklistCategory
from app.services.categorizer import TransactionCategorizer
from app.services.refund_handler import RefundHandler
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
