from fastapi import FastAPI
from app.database import init_db
from app.bot.telegram_bot import create_bot_application, start_bot, stop_bot
from app.config import settings
import asyncio
import logging

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO if settings.debug else logging.WARNING
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Expense Tracker API",
    description="Telegram bot-based expense tracking and billing system",
    version="1.0.0",
)

# Store bot application globally
bot_application = None


@app.on_event("startup")
async def startup_event():
    """Initialize database and start bot on application startup"""
    global bot_application

    logger.info("Starting Expense Tracker application...")

    # Initialize database
    logger.info("Initializing database...")
    init_db()

    # Create and start bot
    logger.info("Creating bot application...")
    bot_application = create_bot_application()

    logger.info("Starting bot polling...")
    await bot_application.initialize()
    await bot_application.start()
    await bot_application.updater.start_polling()

    logger.info("Application startup complete!")


@app.on_event("shutdown")
async def shutdown_event():
    """Stop bot gracefully on application shutdown"""
    global bot_application

    logger.info("Shutting down application...")

    if bot_application:
        logger.info("Stopping bot...")
        await bot_application.updater.stop()
        await bot_application.stop()
        await bot_application.shutdown()

    logger.info("Application shutdown complete.")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "message": "Expense Tracker Bot is active",
        "version": "1.0.0",
    }


@app.get("/health")
async def health():
    """Detailed health check"""
    return {
        "status": "healthy",
        "database": "connected",
        "bot": "running" if bot_application else "not started",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
