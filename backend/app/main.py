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


@app.post("/api/import/{year}/{month}")
async def import_month(year: int, month: int):
    """Import JSON statement files for a billing month."""
    from app.database import SessionLocal
    from app.services.importer import StatementImporter

    if month < 1 or month > 12:
        return {"error": "Month must be between 1 and 12"}

    db = SessionLocal()
    try:
        importer = StatementImporter(db)
        result = importer.import_month(year, month)
        return {
            "billing_month": result.billing_month,
            "files_imported": result.files_imported,
            "files_skipped": result.files_skipped,
            "files_errored": result.files_errored,
            "total_transactions": result.total_transactions,
            "total_flagged": result.total_flagged,
            "total_refunds_matched": result.total_refunds_matched,
            "files": [
                {
                    "filename": fr.filename,
                    "statement_id": fr.statement_id,
                    "transactions": fr.transactions_imported,
                    "flagged": fr.transactions_flagged,
                    "skipped": fr.skipped,
                    "skip_reason": fr.skip_reason,
                    "error": fr.error,
                }
                for fr in result.file_results
            ],
        }
    finally:
        db.close()


@app.get("/api/review/{billing_month}")
async def get_pending_reviews(billing_month: str):
    """Get transactions pending review for a billing month."""
    from app.database import SessionLocal
    from app.models import Transaction

    db = SessionLocal()
    try:
        pending = (
            db.query(Transaction)
            .filter(
                Transaction.billing_month == billing_month,
                Transaction.needs_review == True,
            )
            .order_by(Transaction.transaction_date)
            .all()
        )
        return {
            "billing_month": billing_month,
            "count": len(pending),
            "transactions": [
                {
                    "id": t.id,
                    "date": str(t.transaction_date),
                    "merchant": t.merchant_name,
                    "amount": t.amount,
                    "is_refund": t.is_refund,
                    "categories": t.categories,
                    "method": t.assignment_method,
                }
                for t in pending
            ],
        }
    finally:
        db.close()


@app.post("/api/bills/generate/{billing_month}")
async def generate_bills(billing_month: str):
    """Generate bills for all family members for a billing month."""
    from app.database import SessionLocal
    from app.models import Person
    from app.services.bill_generator import BillGenerator
    from app.services.recurring_charges import RecurringChargesService

    db = SessionLocal()
    try:
        # Generate recurring charges first
        recurring = RecurringChargesService(db)
        recurring.generate_recurring_bills(billing_month)

        # Generate bills for non-self persons
        generator = BillGenerator(db)
        persons = db.query(Person).filter(Person.is_auto_created == False).all()

        results = []
        for person in persons:
            bill = generator.generate_bill(person.id, billing_month)
            if bill:
                results.append({
                    "person": person.name,
                    "total": bill.total_amount,
                    "status": bill.status,
                    "line_items": len(bill.line_items),
                })

        return {"billing_month": billing_month, "bills": results}
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
