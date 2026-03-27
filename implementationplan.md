# Add `card_fees` Category + `/alerts` & `/resolved` Commands

## Context

Bank statements contain charges like LATE CHARGE ASSESSMENT, FINANCE CHARGE, and ANNUAL FEE. These are card-level fees that should:
- Be auto-categorized as `card_fees` during PDF extraction
- NOT trigger the "who to bill to" review (unlike flights, tours, etc.)
- Be auto-assigned to self without review
- Be surfaced via `/alerts` so the user can see them and dispute with the bank
- Be auto-resolved when a matching reversal/credit appears within +2 statement months

## Alert Status Flow

```
Import card fee charge  ──►  pending
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              [User: Resolve] [User: Mark Unresolved] [Auto-resolve on
                    │           │            matching reversal import]
                    ▼           ▼           │
                resolved    unresolved      │
                    │           │           │
                    │     [User: Resolve]   │
                    │           │           │
                    ▼           ▼           ▼
                resolved ◄─────┘───────────┘
                    │
              [User: Unresolve]
                    │
                    ▼
                unresolved
```

**Statuses:**
- `pending` — newly imported, user hasn't acted on it yet
- `unresolved` — user saw it, needs to take action (e.g. call bank to dispute)
- `resolved` — done (manually by user, or auto-matched with reversal)
- `null` — not an alert (normal transaction)

## GST Handling (Option A — Grouped)

Some card fees have a separate GST line (e.g. `ANNUAL FEE $200.00` + `GST ON ANNUAL FEE $18.00`). Design:
- Both lines get `card_fees` category
- GST line: `alert_status = null`, `parent_transaction_id` points to the fee transaction
- Only the parent fee gets `alert_status = 'pending'`
- `/alerts` displays combined total (fee + GST)
- Auto-resolve matches against combined amount (fee + GST) vs reversal amount

**GST detection during import:** Match by same card, same statement, description starts with `GST ON` or `GST FOR`, and a preceding `card_fees` transaction exists. Link via `parent_transaction_id`.

## Auto-Resolve Logic (mirrors refund_handler.py)

Triggered during import when a new `card_fees` transaction with `is_refund=True` (CR/reversal) is found.

**Matching criteria:**
1. Same `card_last_4` (via statement)
2. Fee type match — normalize merchant names to match charge→reversal pairs:
   - `LATE CHARGE ASSESSMENT` ↔ `LATE FEE CREDIT ADJUSTMENT`
   - `FINANCE CHARGE` ↔ `FINANCE CHARGE` (exact, but CR)
   - `ANNUAL FEE` ↔ `ANNUAL FEE REVERSAL` / `ANNUAL FEE WAIVER`
   - Use keyword extraction: strip `ASSESSMENT`, `CREDIT`, `ADJUSTMENT`, `REVERSAL`, `WAIVER` → compare core fee type
3. Amount match — reversal amount = original fee + associated GST (sum of parent + children)
4. Time window — reversal `transaction_date` within +2 months of original fee's `statement_date` (e.g. Jan statement fee → must match by Mar statement)
5. Original fee `alert_status` in (`pending`, `unresolved`) — already-resolved fees are skipped

**Outcomes (mirroring refund_handler pattern):**
- **1 match:** Auto-resolve — set original fee `alert_status='resolved'`, `resolved_by_transaction_id` = reversal txn ID. Set reversal `alert_status='resolved'`. `resolved_method='auto'`.
- **Multiple matches:** Don't auto-resolve — set reversal `alert_status='pending'` so user can manually resolve via `/alerts`.
- **No match:** Set reversal `alert_status='pending'` immediately (good news, mainly for user visibility).

## Files to Modify

### 1. `.claude/commands/guide_extract_statement_command.md`
Add `card_fees` category to the rules table:

| `card_fees` | Merchant name contains: `LATE CHARGE`, `FINANCE CHARGE`, `ANNUAL FEE`, `OVERLIMIT FEE`, `LATE FEE`, `SERVICE CHARGE`, `CARD FEE`; OR Claude's knowledge identifies the charge as a bank/card fee (not a merchant purchase). Reversals of these fees (e.g. `LATE FEE CREDIT ADJUSTMENT` with CR) also get `card_fees`. GST lines for card fees (e.g. `GST ON ANNUAL FEE`) also get `card_fees`. |

### 2. `.claude/commands/banks/hsbc.md`
Update the "Bank Charges" section to note these lines should get `categories: ["card_fees"]`.

### 3. `backend/app/models/transaction.py`
Add columns:
- `alert_status` (nullable String) — `null`, `'pending'`, `'unresolved'`, `'resolved'`
- `parent_transaction_id` (nullable Integer FK → transactions.id) — links GST line to parent fee
- `resolved_by_transaction_id` (nullable Integer FK → transactions.id) — links fee to its reversal
- `resolved_method` (nullable String) — `'manual'` or `'auto'`

### 4. Alembic migration `backend/alembic/versions/004_add_alert_columns.py`
Add all 4 new columns to `transactions` table.

### 5. `backend/app/services/categorizer.py`
In `categorize()`, after the existing waterfall, add:
- If `card_fees` in transaction.categories AND `is_refund == False` → set `alert_status='pending'` on the AssignmentResult
- If `card_fees` in transaction.categories AND `is_refund == True` → set `alert_status=None` (auto-resolve handler will set it later)
- `card_fees` is deliberately NOT in `REVIEW_TRIGGER_CATEGORIES` — no "who to bill to" prompt

Update `AssignmentResult` dataclass to include `alert_status: Optional[str] = None`.

### 6. `backend/app/services/alert_resolver.py` (new file)
New service mirroring `refund_handler.py` structure:

```python
class AlertResolver:
    def __init__(self, db_session):
        self.db = db_session

    def process_card_fee(self, txn: Transaction) -> bool:
        """Called during import for card_fees transactions."""
        if not txn.is_refund:
            # Charge — check if it's a GST line, link to parent
            self._link_gst_if_applicable(txn)
            return False

        # Reversal — try to auto-resolve a pending/unresolved fee
        return self._try_auto_resolve(txn)

    def _link_gst_if_applicable(self, txn):
        """If description starts with 'GST ON'/'GST FOR', find parent fee
        on same card+statement, link via parent_transaction_id,
        set alert_status=None."""

    def _try_auto_resolve(self, reversal_txn):
        """Find matching pending/unresolved fee on same card within
        +2 months. Match by fee type keyword + amount (fee+GST).
        Auto-resolve if exactly 1 match."""

    def _normalize_fee_type(self, merchant_name: str) -> str:
        """Strip ASSESSMENT, CREDIT, ADJUSTMENT, REVERSAL, WAIVER
        to extract core fee type for matching."""

    def _get_fee_total(self, fee_txn: Transaction) -> float:
        """Return fee amount + sum of child GST amounts."""
```

### 7. `backend/app/services/importer.py`
Update `import_file()` to integrate alert_resolver, after existing categorization/refund logic:

```python
# After categorization, apply alert_status from result
txn.alert_status = result.alert_status

# For card_fees transactions, run alert resolver
if 'card_fees' in txn_data.get('categories', []):
    alert_resolver.process_card_fee(txn)
```

Add `alerts_resolved` counter to `ImportResult` for summary reporting.

### 8. `backend/app/bot/handlers.py`
Add two commands:

**`alerts_command` (`/alerts`):**
- Query all transactions where `alert_status IN ('pending', 'unresolved')` AND `parent_transaction_id IS NULL` (exclude GST child lines)
- Order by `transaction_date` DESC
- Group display by card (card_name + last4)
- Each item shows: date, merchant, amount (fee + GST combined), card, bank, status badge (`🆕` pending / `⏳` unresolved)
- Inline keyboard per item: **"✅ Resolve"** (`resolve_{txn_id}`) + **"⏳ Mark Unresolved"** (`unresolved_{txn_id}`)
- If no alerts: "No pending alerts 🎉"

**`resolved_command` (`/resolved`):**
- Query all transactions where `alert_status = 'resolved'` AND `parent_transaction_id IS NULL`
- Order by `transaction_date` DESC, limit to most recent 20
- Each item shows: date, merchant, amount, resolved_method badge (`🤖 auto` / `👤 manual`), linked reversal info if auto-resolved
- Inline keyboard per item: **"↩️ Unresolve"** (`unresolve_{txn_id}`)

**Callback handlers:**
- `resolve_{txn_id}` → set `alert_status='resolved'`, `resolved_method='manual'`, update message
- `unresolved_{txn_id}` → set `alert_status='unresolved'`, update message
- `unresolve_{txn_id}` → set `alert_status='unresolved'`, clear `resolved_method`, update message

Update `/start` and `/help` to list both new commands.

### 9. `backend/app/bot/keyboards.py`
Add keyboard builders:
- `get_alert_keyboard(txn_id)` → "✅ Resolve" + "⏳ Mark Unresolved"
- `get_resolved_keyboard(txn_id)` → "↩️ Unresolve"

### 10. `backend/app/bot/telegram_bot.py`
Register handlers:
- `CommandHandler("alerts", alerts_command)`
- `CommandHandler("resolved", resolved_command)`
- `CallbackQueryHandler` patterns: `resolve_*`, `unresolved_*`, `unresolve_*`

### 11. Update existing HSBC JSON files
Add `"card_fees"` to `categories` for:
- `statements/2026/01/hsbc/...json`: LATE CHARGE ASSESSMENT, FINANCE CHARGE, GST lines
- `statements/2026/02/hsbc/...json`: LATE FEE CREDIT ADJUSTMENT, FINANCE CHARGE (reversals), GST lines

## Key Design Decisions

- `card_fees` is **not** in `REVIEW_TRIGGER_CATEGORIES` — no "who to bill to" prompt
- Card fees are auto-assigned to self (via existing self_auto path)
- `/alerts` shows ALL pending+unresolved across all months (no month filter) — it's a "things I need to act on" view
- `/resolved` is a separate command — keeps `/alerts` clean
- GST lines are grouped with parent fee (Option A) — one alert per fee, not per line
- Auto-resolve window: +2 months from statement_date (Jan fee → must resolve by Mar)
- Auto-resolve mirrors `refund_handler.py` pattern: exact 1 match → auto, multiple → manual, no match → resolve reversal immediately
- Reversals of card fees (CR) also get `card_fees` category — they appear in the resolution chain
- `resolved_method` distinguishes manual vs auto resolution for display

## Verification

1. Check that LATE CHARGE / FINANCE CHARGE / GST transactions in existing JSONs have `categories: ["card_fees"]`
2. Run `alembic upgrade head` to add the new columns
3. Import a month with card fees → verify charges get `alert_status='pending'`, GST lines get `parent_transaction_id` set
4. Import a later month with reversals → verify auto-resolve fires, original fee becomes `resolved`, `resolved_method='auto'`
5. Run `/alerts` in Telegram → verify pending+unresolved card fees appear with combined fee+GST amounts
6. Click "Resolve" → verify `alert_status='resolved'`, `resolved_method='manual'`
7. Click "Mark Unresolved" → verify `alert_status='unresolved'`, still shows in `/alerts`
8. Run `/resolved` → verify resolved items appear with correct badges
9. Click "Unresolve" → verify item moves back to `/alerts`
10. Run `/review` → verify card fee transactions do NOT appear in the review queue
