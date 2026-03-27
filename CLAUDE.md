# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram bot-based expense tracker that parses credit card and bank account PDF statements from Singapore banks (Citi, HSBC, Maybank, UOB), auto-categorizes transactions via card-direct rules and blacklist keyword matching, and generates monthly bills per family member. Built with FastAPI + python-telegram-bot + SQLAlchemy on SQLite.

## Development Commands

All commands run from `backend/`:

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database (interactive - prompts for family member card details)
python setup_database.py

# Start the bot + API server
python run.py

# Import all statement JSONs into DB
python import_statements.py all

# Import specific months
python import_statements.py 2026-01 2026-02

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1
```

Environment config goes in `backend/.env` (copy from `.env.example`). Required: `TELEGRAM_BOT_TOKEN`. The `DATABASE_URL` must use an absolute path to avoid CWD issues.

## Architecture

### Transaction Processing Pipeline

1. **PDF Extraction** via `/extract-statement` Claude Code command -> produces JSON in `statements/YYYY/MM/bank/`
2. **Import** (`services/importer.py`) loads JSON into DB, idempotent via content hash + key-based dedup
3. **Categorization** (`services/categorizer.py`) applies a 3-step waterfall:
   - Card-direct: card_last_4 matches a YAML-defined person -> assign with confidence=1.0
   - Self-default: unknown cards default to auto-created "self" person
   - Blacklist check: "self" transactions matched against keyword categories -> flagged for review if hit
4. **Card fee alerts** (`services/alert_resolver.py`) for `card_fees` category:
   - Links GST child lines to parent fee via `parent_transaction_id`
   - Auto-resolves fee reversals by matching normalized fee type + amount within +2 months
   - Surfaces unresolved fees via `/alerts` Telegram command
5. **Refund matching** (`services/refund_handler.py`) links negative-amount transactions to originals within 90 days by merchant/amount
6. **Recurring charges** (`services/recurring_charges.py`) generates monthly bills from `statements/monthly_payment_to_me.yaml`
7. **Manual review** via Telegram inline buttons for flagged transactions

### Telegram Bot Commands

- `/start`, `/help` — Usage info
- `/review` — Review flagged transactions (assign to family member)
- `/alerts` — View pending/unresolved card fee alerts (late charges, annual fees, etc.)
- `/resolved` — View resolved alerts with option to unresolve
- `/bill YYYY-MM` — Generate monthly bill (planned)

### Key Design Decisions

- **Blacklist over ML for categorization**: The user books flights/tours for both self AND parents from the same merchants, making ML unreliable. Blacklist keywords give explicit user control.
- **Auto-created "self" person**: Cards not in the YAML config default to the user, avoiding the need to list personal cards.
- **`card_fees` not a review trigger**: Card fees (annual fees, late charges, GST) are auto-assigned to self and surfaced via `/alerts` instead of `/review`. They follow a separate alert lifecycle (pending → resolved).
- **GST as separate line items**: GST lines are kept separate in JSON (faithful to statement) and linked to parent fees via `parent_transaction_id`. Combined amounts shown in `/alerts`.
- **Savings account support**: UOB KrisFlyer account statements use `account_number_last_4`/`account_name`/`description` fields — importer falls back to these when `card_last_4`/`card_name`/`merchant_name` are absent.

### Database

SQLite via SQLAlchemy ORM. Core tables: `persons`, `statements`, `transactions`, `assignment_rules`, `blacklist_categories`, `manual_bills`, `bills`, `bill_line_items`. Models in `backend/app/models/`. Full schema documented in `context_sql.md`.

Key transaction columns added in Phase 3:
- `alert_status` — `null` | `pending` | `unresolved` | `resolved`
- `parent_transaction_id` — links GST child to parent fee
- `resolved_by_transaction_id` — links fee to its reversal
- `resolved_method` — `auto` | `manual`

Person/card mappings and blacklist seed data are loaded from `statements/statement_people_identifier.yaml` during `setup_database.py`.

### PDF Statement Extraction

PDF parsing is handled manually via the `/extract-statement` Claude Code custom command rather than automated parsers. This approach avoids fragile PDF parsing and Java dependencies. Supported banks: Citi, HSBC, Maybank, UOB. Note: HSBC statements are image-based PDFs (no extractable text); Claude reads them visually.

Bank-specific rules are in `.claude/commands/banks/`. Category rules are in `.claude/commands/guide_extract_statement_command.md`.

### Services

| Service | File | Purpose |
|---------|------|---------|
| Importer | `services/importer.py` | JSON → DB with dedup, runs categorization pipeline |
| Categorizer | `services/categorizer.py` | Card-direct + self-default + blacklist waterfall |
| Alert Resolver | `services/alert_resolver.py` | Card fee GST linking + auto-resolve reversals |
| Refund Handler | `services/refund_handler.py` | Match refunds to original transactions |
| Recurring Charges | `services/recurring_charges.py` | Monthly bills from YAML config |
| Bill Generator | `services/bill_generator.py` | Per-person bill generation (scaffold) |

## Project Status

- **Phase 1** (complete): Core infrastructure, Telegram bot skeleton, card-direct assignment
- **Phase 2** (complete): Blacklist matching, refund handling, multi-bank support, Telegram review workflow
- **Phase 3** (complete): Card fee alerts, statement importer, recurring charges, savings account support, HSBC bank guide
- **Phase 4** (in progress): Bill generation, statistics dashboard, reporting
