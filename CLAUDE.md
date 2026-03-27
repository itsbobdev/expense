# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram bot-based expense tracker that parses credit card PDF statements from Singapore banks (Citi, HSBC, Maybank, UOB), auto-categorizes transactions via card-direct rules and blacklist keyword matching, and generates monthly bills per family member. Built with FastAPI + python-telegram-bot + SQLAlchemy on SQLite.

## Development Commands

All commands run from `backend/`:

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database (interactive - prompts for family member card details)
python setup_database.py

# Start the bot + API server
python run.py

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1
```

Environment config goes in `backend/.env` (copy from `.env.example`). Required: `TELEGRAM_BOT_TOKEN`.

## Architecture

### Transaction Processing Pipeline

1. **PDF Extraction** via `/extract-statement` Claude Code command -> produces JSON transaction data
2. **Categorization** (`services/categorizer.py`) applies a 3-step waterfall:
   - Card-direct: card_last_4 matches a YAML-defined person -> assign with confidence=1.0
   - Self-default: unknown cards default to auto-created "self" person
   - Blacklist check: "self" transactions matched against keyword categories -> flagged for review if hit
3. **Refund matching** (`services/refund_handler.py`) links negative-amount transactions to originals within 90 days by merchant/amount
4. **Manual review** via Telegram inline buttons for flagged transactions

### Key Design Decisions

- **Blacklist over ML for categorization**: The user books flights/tours for both self AND parents from the same merchants, making ML unreliable. Blacklist keywords give explicit user control.
- **Auto-created "self" person**: Cards not in the YAML config default to the user, avoiding the need to list personal cards.
### Database

SQLite via SQLAlchemy ORM. Core tables: `persons`, `statements`, `transactions`, `assignment_rules`, `blacklist_categories`, `manual_bills`, `bills`, `bill_line_items`. Models in `backend/app/models/`.

Person/card mappings and blacklist seed data are loaded from `statements/statement_people_identifier.yaml` during `setup_database.py`.

### PDF Statement Extraction

PDF parsing is handled manually via the `/extract-statement` Claude Code custom command rather than automated parsers. This approach avoids fragile PDF parsing and Java dependencies. Supported banks: Citi, HSBC, Maybank, UOB. Note: HSBC statements are image-based PDFs (no extractable text); Claude reads them visually.

## Project Status

- **Phase 1** (complete): Core infrastructure, Telegram bot skeleton, card-direct assignment
- **Phase 2** (in progress): Blacklist matching, refund handling, multi-bank support, Telegram review workflow
- **Phase 3** (planned): Dynamic blacklist management, manual recurring bills, billing engine
- **Phase 4** (future): Bill generation, statistics dashboard, reporting
