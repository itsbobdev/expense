from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from app.bot.handlers import (
    start_command,
    help_command,
    upload_command,
    handle_document,
    handle_callback,
    stats_command,
)
from app.config import settings
import logging

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def create_bot_application() -> Application:
    """
    Create and configure the Telegram bot application.

    Returns:
        Configured Application instance
    """
    # Create application
    application = Application.builder().token(settings.telegram_bot_token).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CommandHandler("stats", stats_command))

    # Register message handlers
    application.add_handler(MessageHandler(filters.Document.PDF, handle_document))

    # Register callback query handler for inline keyboards
    application.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Bot application created and handlers registered")

    return application


async def start_bot():
    """Start the bot using polling"""
    application = create_bot_application()

    logger.info("Starting bot...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    logger.info("Bot is running. Press Ctrl+C to stop.")


async def stop_bot(application: Application):
    """Stop the bot gracefully"""
    logger.info("Stopping bot...")
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    logger.info("Bot stopped.")


if __name__ == "__main__":
    import asyncio

    # Run the bot
    app = create_bot_application()
    app.run_polling()
