"""
Simple run script for the expense tracker bot.

Usage:
    python run.py
"""

import uvicorn
from app.config import settings

if __name__ == "__main__":
    print("="*60)
    print("Starting Expense Tracker Bot")
    print("="*60)
    print(f"\nHost: {settings.app_host}")
    print(f"Port: {settings.app_port}")
    print(f"Debug: {settings.debug}")
    print(f"Database: {settings.database_url}")
    print("\nPress Ctrl+C to stop the server")
    print("="*60 + "\n")

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
