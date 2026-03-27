# Expense Allocation Process

End-to-end pipeline for importing credit card transactions, assigning them to family members, and generating monthly bills.

## Pipeline Overview

```
JSON Files  →  Import  →  Categorize  →  Refund Match  →  Telegram Review  →  Monthly Recurring  →  Bill Generation
(statements/     (DB)      (auto-assign)   (link refunds)   (manual decisions)   (YAML charges)      (per-person totals)
 YYYY/MM/bank/)
```

### Stage 1: Import

Load JSON statement files from `statements/YYYY/MM/bank/*.json` into the database.

**Billing month** is derived from the **folder path** (`YYYY/MM`), not from `statement_date` or `transaction_date`. This is critical because a single statement can span months and a transaction may post in a different month than it occurred.

Each JSON file creates:
- One `Statement` record (bank_name, card_last_4, card_name, statement_date, period_start, period_end)
- One `Transaction` record per entry (merchant_name, amount, is_refund, etc.)

The statement's `billing_month` field (format: `"2026-03"`) is set from the folder path. Duplicate detection uses `pdf_hash` or the combination of (bank_name, card_last_4, statement_date) to prevent re-import.

### Stage 2: Categorize

`TransactionCategorizer` runs a 3-step waterfall on each non-refund transaction:

1. **Card-direct**: Card's last-4 digits match a person in `statement_people_identifier.yaml` → assigned with confidence=1.0, `method='card_direct'`, `needs_review=False`
2. **Self-default**: Unmatched cards → auto-created "self" person (foo_chi_jao's own cards)
3. **Category review check**: For "self" transactions, check if the JSON `categories` array contains any of the 9 trigger categories → flag for Telegram review

#### The 9 Trigger Categories

All 9 categories trigger `needs_review=True` on self-card transactions because these are expenses that *could* be for dad or wife:

| Category | Why it triggers review |
|----------|----------------------|
| `flights` | Books flights for parents |
| `tours` | Books tours for parents |
| `travel_accommodation` | Books hotels for parents |
| `subscriptions` | Some subscriptions shared |
| `foreign_currency` | Foreign purchases may be for anyone |
| `amaze` | Amaze top-ups could be for anyone |
| `paypal` | PayPal purchases could be for anyone |
| `insurance` | Pays insurance for parents |
| `town_council` | Pays town council for dad |

**Category source**: The `categories` array is set during PDF extraction (in the JSON file). The categorizer checks this array rather than re-running blacklist keyword matching — the extraction step already classified the merchant.

**Card-direct transactions skip category review entirely.** If a card belongs to dad, every transaction on it is dad's — even flights or tours.

### Stage 3: Refund Match

`RefundHandler` processes transactions where `is_refund=True` (negative amount):

1. Search for original transaction: same `merchant_name`, exact matching positive amount, within **180-day** window before refund date
2. **1 match** → auto-assign refund to same person as original (`method='refund_auto_match'`, confidence=0.95)
3. **Multiple matches** → flag for Telegram review (`method='refund_ambiguous'`)
4. **No match** → flag for Telegram review (`method='refund_orphan'`)

**Cross-month refunds**: A refund in March for a January purchase is normal. The refund appears as a **negative line item in March's bill** — no retroactive amendment to January's bill.

### Stage 4: Telegram Review

Transactions with `needs_review=True` are sent to the Telegram bot for manual resolution.

#### Review Queue Message Format

```
📋 Review needed: 5 transactions for 2026-03

1/5: SINGAPORE AIRLINES $850.00
  Card: UOB ****5993 (self)
  Category: flights
  Date: 2026-03-15
  [Dad] [Wife] [Mine] [Skip]
```

#### Review Actions

| Button | Effect |
|--------|--------|
| **[Dad]** / **[Wife]** / **[Mine]** | Sets `assigned_to_person_id`, `needs_review=False`, `assignment_method='manual'`, `reviewed_at=now` |
| **[Skip]** | Keeps `needs_review=True`, skipped for now (can review later) |

#### Refund Review (Ambiguous/Orphan)

For refunds needing review, show the refund with candidate originals:

```
🔄 Refund match needed:

Refund: KLOOK -$150.00 (2026-03-10)

Possible originals:
  1. KLOOK $150.00 (2026-01-15) → assigned to: Dad
  2. KLOOK $150.00 (2025-12-20) → assigned to: Wife

[Match #1] [Match #2] [Assign to self]
```

For orphan refunds (no candidates):
```
🔄 Orphan refund:

BOOKING.COM -$200.00 (2026-03-10)
No matching original found.

[Dad] [Wife] [Mine]
```

#### Telegram Commands

| Command | Purpose |
|---------|---------|
| `/review` | Show pending review queue for current month |
| `/review 2026-01` | Show pending reviews for a specific month |
| `/bill 2026-03` | Generate/preview bill for a month |
| `/status` | Show import/review/bill status summary |

### Stage 5: Monthly Recurring Charges

Fixed monthly charges from `statements/monthly_payment_to_me.yaml` are added as `ManualBill` records each billing month. These are expenses paid by the user on behalf of family members that don't appear on credit card statements (or appear on the user's card but should be billed to someone else).

See [YAML format](#monthly-recurring-yaml-format) below.

### Stage 6: Bill Generation

Generate a per-person bill for each billing month.

#### Bill Assembly Logic

For each person (dad, wife) in a given billing month:

1. **Credit card transactions**: All `Transaction` records where `assigned_to_person_id = person.id` and `billing_month = target_month`
2. **Refunds**: Negative-amount transactions assigned to this person in this billing month (appear as negative line items)
3. **Monthly recurring**: `ManualBill` records for this person in this billing month
4. **Total** = sum of all line items (transactions + refunds + manual bills)

#### Bill Output Format (Telegram)

```
📊 Bill for Dad — March 2026

Credit Card Charges:
  03/01 NTUC FAIRPRICE          $45.20  (Maybank ****0005)
  03/05 SINGAPORE AIRLINES     $850.00  (UOB ****5993)
  03/12 COLD STORAGE            $32.50  (Citi ****6265)

Refunds:
  03/10 KLOOK                  -$150.00  (UOB ****5993)

Monthly Recurring:
  HDB Season Parking           $110.00  (Chocolate ****9551)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total:                         $887.70

[Finalize] [Edit]
```

#### Bill States

| Status | Meaning |
|--------|---------|
| `draft` | Auto-generated, editable |
| `finalized` | Locked, sent to person |
| `sent` | Delivered via Telegram |

#### Finalization Rules

- A bill can only be finalized when **all transactions for that person/month have `needs_review=False`**
- Finalizing sets `finalized_at` timestamp and prevents further changes
- If new transactions are imported for an already-finalized month, the bill reverts to `draft`

---

## Monthly Recurring YAML Format

**File**: `statements/monthly_payment_to_me.yaml`

```yaml
people:
  - name: foo_wah_liang        # must match name in statement_people_identifier.yaml
    items:
      hdb_season_parking:
        description: "HDB Season Parking at Blk XXX"
        card_used: "chocolate 9551"
        amount: 110.00
        effective_from: "2024-01"       # billing month this charge starts (inclusive)
        effective_until: null            # null = ongoing, or "2026-06" to end

      sp_utilities:
        description: "SP Group Utilities"
        card_used: "giro"
        amount: 150.00
        effective_from: "2024-01"
        effective_until: null

  - name: chan_zelin
    items:
      phone_plan:
        description: "Singtel Mobile Plan"
        card_used: "giro"
        amount: 45.00
        effective_from: "2025-06"
        effective_until: null
```

**Field reference**:

| Field | Required | Description |
|-------|----------|-------------|
| `description` | Yes | Human-readable label for the bill line item |
| `card_used` | Yes | Payment method (informational only, not matched to DB) |
| `amount` | Yes | Monthly amount in SGD |
| `effective_from` | Yes | First billing month (inclusive), format `"YYYY-MM"` |
| `effective_until` | No | Last billing month (inclusive), `null` = ongoing |

When generating a bill for month `M`, include the item if `effective_from <= M` and (`effective_until` is null or `effective_until >= M`).

---

## Edge Cases

### Import Edge Cases

| Situation | Resolution |
|-----------|-----------|
| Same PDF imported twice | Reject duplicate via `pdf_hash` check |
| Transaction date outside statement period | Normal (e.g., Dec 31 charge on Jan statement). Billing month = folder month, not transaction date |
| Statement spans two months | Billing month = folder month. All transactions in the file belong to that month |
| Former card (e.g., UOB ****6691) | `former_cards` in YAML includes `last_active` date. Card-direct still matches if the statement period overlaps |

### Categorization Edge Cases

| Situation | Resolution |
|-----------|-----------|
| Self-card transaction with no category match | Auto-assigned to self, `needs_review=False` — it's a normal personal expense |
| Self-card transaction in multiple categories | Any single category hit triggers review. Category stored as the first match |
| Card in YAML belongs to dad, transaction is a flight | No review — card-direct overrides. Dad's card = dad's expense, always |
| New card not in YAML | Defaults to self. User should update YAML and re-run setup |

### Refund Edge Cases

| Situation | Resolution |
|-----------|-----------|
| Refund on dad's card (card-direct) | Card-direct assigns to dad. Refund handler also links to original if found. Both agree |
| Refund on self-card for dad's expense | Refund handler finds original (assigned to dad) → auto-assigns refund to dad |
| Partial refund (different amount) | No auto-match (amounts must be exact). Flagged as orphan for manual review |
| Refund older than 180 days | No auto-match. Flagged as orphan |
| Refund with no original (credit/goodwill) | Flagged as orphan. Manual assignment via Telegram |

### Billing Edge Cases

| Situation | Resolution |
|-----------|-----------|
| All transactions reviewed but total is $0 | Still generate bill (shows activity but net zero) |
| Recurring charge amount changes | Add new item with `effective_from` at the new rate; set `effective_until` on old item |
| Mid-month recurring charge start | Use the month it starts. No proration — full amount from `effective_from` month |
| Person has no transactions for a month | Bill only includes monthly recurring items (if any) |
| Finalized bill gets new transactions | Bill reverts to `draft`, user notified via Telegram |

---

## Code Changes Needed

### New/Modified Models

**`backend/app/models/statement.py`** — Add `billing_month` column:
```python
billing_month = Column(String, nullable=False, index=True)  # "2026-03"
```

**`backend/app/models/transaction.py`** — Add `billing_month` (denormalized from statement for query convenience):
```python
billing_month = Column(String, nullable=False, index=True)  # "2026-03"
```

### New/Modified Services

**`backend/app/services/importer.py`** (new) — JSON import service:
- `import_month(year, month)` — scan `statements/YYYY/MM/` folders, import all JSON files
- `import_file(json_path, billing_month)` — import single JSON, create Statement + Transactions
- Duplicate detection via pdf_hash or (bank, card_last_4, statement_date)

**`backend/app/services/categorizer.py`** (modify):
- Change blacklist check to category array check: read `categories` from JSON/transaction instead of re-running keyword matching
- Keep the same 3-step waterfall but step 3 checks `transaction.category` against the 9 trigger categories

**`backend/app/services/refund_handler.py`** (modify):
- Change window from 90 days to **180 days**
- Add cross-statement search (current code already searches by date, not statement)

**`backend/app/services/recurring_charges.py`** (new):
- `load_recurring_config()` — parse `monthly_payment_to_me.yaml`
- `generate_recurring_bills(billing_month)` — create `ManualBill` records for active items in the given month
- Idempotent: skip if ManualBill already exists for (person, description, billing_month)

**`backend/app/services/bill_generator.py`** (new):
- `generate_bill(person_id, billing_month)` — assemble Bill + BillLineItems from transactions + manual bills
- `finalize_bill(bill_id)` — lock bill, check all transactions reviewed
- `format_bill_message(bill_id)` — Telegram-formatted bill text

### New/Modified Handlers

**`backend/app/bot/handlers.py`** (modify):
- Add `/review [YYYY-MM]` command — show pending review queue
- Add `/bill [YYYY-MM]` command — generate/preview bill
- Add `/status` command — summary of pipeline state
- Modify `handle_callback` for refund match buttons (`match_refund_{refund_id}_{original_id}`)

### New Migration

**`backend/alembic/versions/003_add_billing_month.py`**:
- Add `billing_month` to `statements` and `transactions` tables
- Backfill existing records if needed (derive from created_at or manual mapping)

### New API Endpoints (optional, for future web UI)

- `POST /api/import/{year}/{month}` — trigger import for a month
- `GET /api/review/{billing_month}` — get pending reviews
- `POST /api/bills/generate/{billing_month}` — generate bills
- `GET /api/bills/{person_id}/{billing_month}` — get bill details

---

## Implementation Phases

### Phase A: Import + Categorize
1. Add `billing_month` column (migration 003)
2. Build `importer.py` service
3. Modify categorizer to use JSON `categories` array for the 9-category trigger
4. Test: import a month of JSON files, verify card-direct and category-triggered assignments

### Phase B: Refund Matching
1. Update refund handler to 180-day window
2. Wire refund processing into the import pipeline (run after categorization)
3. Test: import statements with known refunds, verify auto-match and orphan detection

### Phase C: Telegram Review
1. Add `/review` command and review queue rendering
2. Add refund-specific review UI (candidate matching buttons)
3. Test: trigger review flow via Telegram, verify assignment updates

### Phase D: Monthly Recurring + Bills
1. Build `recurring_charges.py` service
2. Expand `monthly_payment_to_me.yaml` format (done — see below)
3. Build `bill_generator.py` service
4. Add `/bill` command to Telegram
5. Test: generate bill for a month with transactions + refunds + recurring charges

### Verification Approach

For each phase:
1. Import known test data from `statements/test/`
2. Verify database state (correct assignments, review flags, billing months)
3. Run Telegram bot locally, walk through review flow
4. Generate bills and compare against manually calculated expected totals
