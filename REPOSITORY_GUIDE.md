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

# Export/import DB-only live state
python export_live_state.py
python import_live_state.py

# Build the offline Mac handoff package
python build_handoff_package.py

# From repo root, refresh corrected statement JSONs safely
python .codex/skills/expense-refresh-statement-db/scripts/refresh_statement_db.py statements/2026/02/uob/file.json

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1
```

Environment config goes in `backend/.env` copied from `backend/.env.example` or the repo-root `.env.example`. `TELEGRAM_BOT_TOKEN` is required. The runtime always loads `backend/.env`; repo-root `.env` is intentionally unsupported.

## Core Workflow

1. Statement PDFs are organized under `statements/YYYY/MM/bank/`.
2. Transactions are extracted from PDFs into JSON files stored alongside the source PDFs.
3. If an existing JSON is corrected or replaced, the DB must be updated through `$expense-refresh-statement-db`.
4. The importer validates extracted JSON before commit, including UOB credit-card sidecar PDF checks for mandatory non-payment `... CR` rows when the source PDF is available.
5. The importer loads extracted JSON into the database with deduplication.
6. Categorization and assignment rules run during import.
7. Flagged transactions are reviewed in Telegram.
8. Manual bill items can be added in Telegram with `/add_expense`.
9. Bills and alerts are generated from imported transactions plus manual bill items.
10. Before committing DB-only work state such as review decisions, shared splits, manual bill items, or bill records, export `state/live_state.json` with `python export_live_state.py`.

## Architecture

### Transaction Processing Pipeline

1. **PDF extraction** produces statement JSON in `statements/YYYY/MM/bank/`.
2. **Import** in `services/importer.py` loads JSON into the DB with content-hash and key-based deduplication.
3. **Categorization** in `services/categorizer.py` applies a 3-step waterfall:
   - Card-direct: `card_last_4` matches a YAML-defined person.
   - Self-default: unknown cards default to the auto-created `self` person.
   - Blacklist check: `self` transactions matched against keyword categories are flagged for review.
4. **Alerts** in `services/alert_policy.py` and `services/alert_resolver.py`:
   - `alert_kind = card_fee` for `card_fees` transactions.
   - `alert_kind = high_value` for non-reward transactions with `abs(amount) > 111`.
   - Account-style statements only create `high_value` alerts for rows persisted as `transaction_type = debit`; account credits are excluded.
   - Link GST child lines via `parent_transaction_id`.
   - Auto-resolve fee reversals only for `card_fee` alerts by normalized fee type and amount within +2 months.
   - HSBC late-fee reversals treat `LATE CHARGE` and `LATE FEE` labels as the same fee family for auto-resolution.
   - Surface pending and unresolved alerts through `/alerts`, including card owner names when configured.
5. **Refund matching** in `services/refund_handler.py` links negative transactions to originals within 90 days by merchant and amount.
   - A matched refund drops out of `/refund`, but the original charge can still remain in `/review` if it separately triggered category review.
   - Linked refunds follow the original charge's latest assignment or shared split, so reassignment order does not matter.
   - If the original charge is moved back into review, its linked refund becomes pending again and reappears in `/refund` without losing the original link.
   - Bills show matched refunds as separate negative ledger lines under `Refunds:` rather than netting them into the original charge, even when the refund is shared.
6. **Recurring charges** in `services/recurring_charges.py` generate monthly bills from `statements/monthly_payment_to_me.yaml`.
7. **Manual bill items** in `manual_bills` include two persisted types:
   - `recurring` for seeded recurring charges such as parking.
   - `manually_added` for ad hoc Telegram-added expenses created through `/add_expense`.
8. **Manual review** happens through Telegram inline buttons.
9. **Account-style statements** imported from JSON `account_*` fields are sign-normalized in the DB so outgoing debits become positive charges, and they do not participate in refund matching.

### Telegram Commands

- `/start`, `/help` - Usage info
- `/review` - Review flagged transactions
- `/refund [YYYY-MM]` - Review pending refunds, including orphan or ambiguous refunds plus linked refunds waiting on original-charge review
- `/alerts` - View pending or unresolved alerts, including card fees and high-value non-reward transactions
- `/resolved` - View resolved alerts with option to unresolve
- `/bill YYYY-MM` - Generate monthly bill
- `/add_expense` - Add a manual expense to a person's bill
- `/cancel` - Cancel the current guided add-expense flow

### Manual Bill Behavior

- `/add_expense` creates a `manual_bills` row with `manual_type = manually_added`.
- Seeded recurring charges continue to use `manual_type = recurring`.
- Bill output shows recurring manual items under `Monthly Recurring:` and Telegram-added items under `Manually Added:`.
- Draft bill messages include inline remove buttons for `Manually Added` items only.
- Finalized and paid bills stay locked; manually added items cannot be removed from those bill states.

## Data and File Conventions

- Statement PDFs and extracted JSON live under `statements/YYYY/MM/bank/`.
- Git tracks extracted statement JSON plus `statements/statement_people_identifier.yaml`, `statements/monthly_payment_to_me.yaml`, and `statements/rewards_history.json`.
- Raw statement PDFs remain private and are excluded from git-backed regular workflow state.
- DB-only review, split, manual-bill, and bill state is committed via `state/live_state.json`, not by checking in SQLite files.
- Person/card mappings and blacklist seed data come from `statements/statement_people_identifier.yaml`.
- Full schema notes are in `context_sql.md`.
- Core tables include `persons`, `statements`, `transactions`, `assignment_rules`, `blacklist_categories`, `manual_bills`, `bills`, and `bill_line_items`.

Key `manual_bills` columns:

- `manual_type`: `recurring` | `manually_added`

Key transaction columns added in Phase 3:

- `alert_kind`: `null` | `card_fee` | `high_value`
- `alert_status`: `null` | `pending` | `unresolved` | `resolved`
- `transaction_type`: `null` | `debit` | `credit` (persisted for account-style statements)
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
- Do not skip non-payment UOB credit-card rows just because the SGD amount ends with `CR`; merchant refunds, dispute credits, and fee waivers are mandatory transactions unless they are reward credits or payment lines.
- When a corrected existing statement JSON is refreshed, the importer should fail loudly if required UOB non-payment `CR` rows from the source PDF are missing or mis-signed.
- Keep statement organization under `statements/YYYY/MM/bank/`.

### Git-Backed Working State

- Commit extracted statement JSON, statement config YAML, rewards history, and `state/live_state.json` when you want another machine to reproduce the current working state after clone.
- Do not commit SQLite databases, raw statement PDFs, `.env` files, or credential JSONs.
- To rebuild from git-backed data on a fresh machine:
  1. create `backend/.env`
  2. run migrations
  3. seed people/rules/blacklist with `python setup_database.py`
  4. import tracked statement JSON with `python import_statements.py --skip-recurring-charges --allow-validation-errors all`
  5. import tracked `rewards_history.json`
  6. apply `state/live_state.json` with `python import_live_state.py`

### Shared Rule Sources

- Bank-specific parsing rules: `.claude/commands/banks/`
- Extraction categorization guide: `.claude/commands/guide_extract_statement_command.md`
- Claude execution shortcut: `.claude/commands/extract-statement.md`
- Claude organization shortcut: `.claude/commands/organise-statements.md`

These files are the current source of truth for parsing and output rules. Claude uses them as native command surfaces. Codex and manual workflows should use them as reference documentation unless and until a separate native Codex workflow is added.

## Key Design Decisions

- Blacklist matching is preferred over ML for ambiguous shared merchants such as flights and tours.
- Unknown cards default to the `self` person to avoid over-configuring personal cards.
- `card_fees` do not go through the normal review queue; they use `alert_kind = card_fee` and follow a separate alert lifecycle.
- `/alerts` is the shared alert queue for both card-fee alerts and manual-ack high-value non-reward transactions above `$111`.
- High-value alerts apply across configured card owners such as `foo_chi_jao`, `foo_wah_liang`, and `chan_zelin`; Telegram alert messages should show the configured owner when available.
- GST remains as separate statement-faithful lines and is linked to parent fees.
- UOB savings account support falls back to account-level fields when card fields are absent.
- Account-style statement JSON may keep bank-native debit/credit signs, but the importer normalizes them for DB billing semantics.
- Account-style statement credits such as transfers or interest must not become `high_value` alerts; only persisted debit rows are eligible there.
- UOB credit-card `SUB TOTAL` values are not a safe universal transaction-sum validator in this repo because they can include carried balances or payments; UOB import validation relies on source-PDF credit-row checks instead.

## Compatibility Notes

- `CLAUDE.md` is for Claude Code.
- `AGENTS.md` is for Codex/OpenAI agents.
- `.claude/settings.local.json`, `.claude/logs/`, and `.claude/backups/` are Claude-local artifacts and are not shared configuration.
- When shared workflow behavior changes, update this document first and then mirror any necessary tool-specific wording intentionally.
