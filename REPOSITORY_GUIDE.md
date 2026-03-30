# Repository Guide

This document contains shared repo guidance that applies regardless of whether work is being done in Claude Code, Codex, or manually by a person.

## Project Overview

Telegram bot-based expense tracker that parses credit card and bank account PDF statements from Singapore banks (Citi, HSBC, Maybank, UOB), auto-categorizes transactions via card-direct rules and blacklist keyword matching, and generates monthly bills per family member. The backend is built with FastAPI, python-telegram-bot, SQLAlchemy, and SQLite.

## Development Commands

Run these from `backend/` unless noted otherwise:

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database (interactive)
python setup_database.py

# Start the bot + API server
python run.py

# Import all extracted statement JSON into the DB
python import_statements.py all

# Import specific months
python import_statements.py 2026-01 2026-02

# From repo root, refresh corrected statement JSONs safely
python .codex/skills/expense-refresh-statement-db/scripts/refresh_statement_db.py statements/2026/02/uob/file.json

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1
```

Environment config goes in `backend/.env` copied from `.env.example`. `TELEGRAM_BOT_TOKEN` is required. Use an absolute path for `DATABASE_URL` to avoid working-directory issues.

## Core Workflow

1. Statement PDFs are organized under `statements/YYYY/MM/bank/`.
2. Transactions are extracted from PDFs into JSON files stored alongside the source PDFs.
3. If an existing JSON is corrected or replaced, the DB must be updated through `$expense-refresh-statement-db`.
4. The importer loads extracted JSON into the database with deduplication.
5. Categorization and assignment rules run during import.
6. Flagged transactions are reviewed in Telegram.
7. Bills and alerts are generated from the imported transaction data.

## Architecture

### Transaction Processing Pipeline

1. **PDF extraction** produces statement JSON in `statements/YYYY/MM/bank/`.
2. **Import** in `services/importer.py` loads JSON into the DB with content-hash and key-based deduplication.
3. **Categorization** in `services/categorizer.py` applies a 3-step waterfall:
   - Card-direct: `card_last_4` matches a YAML-defined person.
   - Self-default: unknown cards default to the auto-created `self` person.
   - Blacklist check: `self` transactions matched against keyword categories are flagged for review.
4. **Card fee alerts** in `services/alert_resolver.py`:
   - Link GST child lines via `parent_transaction_id`.
   - Auto-resolve fee reversals by normalized fee type and amount within +2 months.
   - HSBC late-fee reversals treat `LATE CHARGE` and `LATE FEE` labels as the same fee family for auto-resolution.
   - Surface unresolved fees through `/alerts`.
5. **Refund matching** in `services/refund_handler.py` links negative transactions to originals within 90 days by merchant and amount.
6. **Recurring charges** in `services/recurring_charges.py` generate monthly bills from `statements/monthly_payment_to_me.yaml`.
7. **Manual review** happens through Telegram inline buttons.
8. **Account-style statements** imported from JSON `account_*` fields are sign-normalized in the DB so outgoing debits become positive charges, and they do not participate in refund matching.

### Telegram Commands

- `/start`, `/help` - Usage info
- `/review` - Review flagged transactions
- `/alerts` - View pending or unresolved card fee alerts
- `/resolved` - View resolved alerts with option to unresolve
- `/bill YYYY-MM` - Generate monthly bill

## Data and File Conventions

- Statement PDFs and extracted JSON live under `statements/YYYY/MM/bank/`.
- Person/card mappings and blacklist seed data come from `statements/statement_people_identifier.yaml`.
- Full schema notes are in `context_sql.md`.
- Core tables include `persons`, `statements`, `transactions`, `assignment_rules`, `blacklist_categories`, `manual_bills`, `bills`, and `bill_line_items`.

Key transaction columns added in Phase 3:

- `alert_status`: `null` | `pending` | `unresolved` | `resolved`
- `parent_transaction_id`: links GST child to parent fee
- `resolved_by_transaction_id`: links fee to its reversal
- `resolved_method`: `auto` | `manual`

## Statement Extraction Expectations

The extraction workflow is manual and produces structured JSON that the importer consumes. The execution mechanism can vary by tool, but the output contract should stay consistent.

### Post-Correction DB Rule

- When an existing statement JSON is corrected, re-extracted, or replaced, the database update must go through `$expense-refresh-statement-db`.
- Do not use an ad hoc normal `import_statements.py` run for corrected existing statement files.
- The refresh skill decides whether each file should be refreshed or imported normally by checking the real statement identity already present in the backend DB.
- Use normal import directly only for broad month/all imports that are not part of a corrected-statement repair workflow.

### Required Behavior

- Extract every statement PDF in the target folder.
- Produce one or more JSON objects per statement depending on card/account sections.
- Save each JSON object alongside the source PDF using the repo's filename convention.
- Preserve bank-specific parsing behavior for Citi, HSBC, Maybank, and UOB.
- Apply categorization rules so transactions include the expected `categories` array.
- Keep statement organization under `statements/YYYY/MM/bank/`.

### Shared Rule Sources

- Bank-specific parsing rules: `.claude/commands/banks/`
- Extraction categorization guide: `.claude/commands/guide_extract_statement_command.md`
- Claude execution shortcut: `.claude/commands/extract-statement.md`
- Claude organization shortcut: `.claude/commands/organise-statements.md`

These files are the current source of truth for parsing and output rules. Claude uses them as native command surfaces. Codex and manual workflows should use them as reference documentation unless and until a separate native Codex workflow is added.

## Key Design Decisions

- Blacklist matching is preferred over ML for ambiguous shared merchants such as flights and tours.
- Unknown cards default to the `self` person to avoid over-configuring personal cards.
- `card_fees` do not go through the normal review queue; they follow a separate alert lifecycle.
- GST remains as separate statement-faithful lines and is linked to parent fees.
- UOB savings account support falls back to account-level fields when card fields are absent.
- Account-style statement JSON may keep bank-native debit/credit signs, but the importer normalizes them for DB billing semantics.

## Compatibility Notes

- `CLAUDE.md` is for Claude Code.
- `AGENTS.md` is for Codex/OpenAI agents.
- `.claude/settings.local.json`, `.claude/logs/`, and `.claude/backups/` are Claude-local artifacts and are not shared configuration.
- When shared workflow behavior changes, update this document first and then mirror any necessary tool-specific wording intentionally.
