# Expense Tracking & Billing System - Implementation Plan (REVISED)

> **Last Updated:** March 2026
> **Status:** Phase 1 Complete, moving to Phase 2

## Overview

Build a **Telegram bot-based expense tracker** to automatically bill parents and spouse based on credit card statements. The system will parse PDF statements, categorize transactions using **blacklist-based rules**, handle refunds, and generate monthly bills.

**Key Change:** Original plan used ML categorization, but revised to use blacklist-based manual review for better accuracy and user control.

## User Requirements Summary

**Input:** Credit card statements (PDF format)
**Output:** Bills for parents and spouse via Telegram
**Platform:** Telegram bot (mobile-first, cloud-hosted)
**Timeline:** 2-3 weeks for MVP

### Business Logic Scenarios

1. **Easy:** Supplementary cards in YAML → Direct billing (card in YAML → that person)
2. **Easy:** Cards NOT in YAML → Auto-assign to "self"
3. **Hard:** Self's main card transactions → Blacklist-based manual review
   - Blacklist categories trigger manual review: flights, tours, travel accommodations, foreign currency, AMAZE* transactions
   - All other self transactions auto-assign to self
   - User can dynamically add new blacklist categories via Telegram
4. **Hard:** Merchant refunds → Auto-match to original transaction and assign to same person
5. **New:** Fixed recurring bills not in statements → Manual entry via Telegram, included in final expense report

## Technology Stack

- **Backend:** FastAPI (Python 3.11)
- **Bot:** python-telegram-bot
- **Database:** SQLite (MVP) → PostgreSQL (production)
- **PDF Extraction:** Claude Code custom slash command `/extract-statement` (manual workflow)
- **Categorization:** Keyword-based blacklist matching (no ML)
- **Deployment:** Railway or Render (cloud hosting, free tier)

## Database Schema (Core Tables)

**persons** - Family members (from YAML + auto-created "self")
- id, name, relationship_type, card_last_4_digits[]
- is_auto_created (boolean, true for "self" person)

**statements** - Uploaded credit card statements
- id, filename, card_last_4, statement_date, status, raw_file_path

**transactions** - Individual transactions from statements
- id, statement_id, date, merchant_name, amount, is_refund, location
- category, assigned_to_person_id, assignment_confidence, assignment_method
- needs_review (boolean), reviewed_at, blacklist_category_id

**assignment_rules** - Card-direct assignment rules
- id, priority, rule_type (card_direct only)
- conditions (JSON: {card_last_4: "1234"}), assign_to_person_id

**blacklist_categories** - Categories that trigger manual review for "self" transactions
- id, name (e.g., "flights", "tours", "accommodation", "foreign_currency", "amaze")
- keywords (JSON array: ["jetstar", "scoot", "changi airport"])
- is_active (boolean)

**manual_bills** - Fixed recurring bills NOT from statements
- id, person_id, amount, description, billing_month, created_at

**bills** - Generated monthly bills for each person
- id, person_id, period_start, period_end, total_amount, status

**bill_line_items** - Line items in bills (from transactions + manual_bills)
- id, bill_id, transaction_id, manual_bill_id, amount, description

## Implementation Phases

### Phase 1: Core Infrastructure ✅ COMPLETE

**Implemented:**
- ✅ FastAPI project structure
- ✅ SQLite database with SQLAlchemy + Alembic migrations
- ✅ Core models (Person, Statement, Transaction, Rule, Bill)
- ✅ YAML loader for person/card mappings
- ✅ Database seeding from YAML (not interactive prompts)
- ✅ Claude Code custom slash command `/extract-statement` for manual PDF extraction
- ✅ Telegram bot skeleton
- ✅ Conda environment setup

**Note:** PDF extraction is now manual via `/extract-statement` command instead of automated parsing

**Current Setup:**
- Persons from YAML: foo_wah_liang (5 cards), chan_zelin (2 cards)
- Test statements: 3 PDFs (Maybank World MC, Maybank F&F, UOB multi-card)
- YAML file gitignored for security

### Phase 2: Blacklist System & Review Workflow (IN PROGRESS)

**Tasks:**
1. Add blacklist_categories and manual_bills tables (Alembic migration)
2. Implement BlacklistMatcher service for keyword matching
3. Seed initial blacklist categories (flights, tours, accommodation, foreign_currency, amaze)
4. Update TransactionCategorizer to check blacklist for "self" transactions
5. Implement Telegram review workflow with inline buttons
6. Add callback handlers for manual assignment
7. Implement refund matching algorithm

**Deliverables:**
- ✅ Blacklist categories trigger manual review for "self" transactions
- ✅ Refunds auto-match to original transactions
- ✅ Telegram review prompts show blacklist match reason
- ✅ Manual assignments update transaction records correctly

### Phase 3: Dynamic Blacklist & Manual Bills

**Tasks:**
1. `/blacklist` command - View all blacklist categories and keywords
2. `/add_blacklist` command - Add new category or keywords
3. Add "📋 Add to blacklist" button in review workflow
4. `/add_recurring_bill` command - Add fixed monthly bills
5. `/recurring_bills` command - List all manual bills
6. Update billing engine to include manual bills

### Phase 4: Billing Engine & Polish

**Tasks:**
1. Billing engine: Generate bills from transactions + manual bills
2. Telegram bill formatting with separate sections
3. Additional commands: /stats, /export
4. Comprehensive testing with real statements
5. Documentation and deployment

## PDF Extraction Workflow

**Manual Extraction via Claude Code:**

1. **Place PDFs:** User manually places statement PDFs in `statements/` folder (organized by bank)
2. **Run Command:** User runs `/extract-statement statements/[bank_name]/` in Claude Code
3. **Get JSON:** Claude Code reads PDFs and outputs structured JSON with transactions
4. **Manual Entry:** User reviews JSON and inputs/imports data into system

**Benefits:**
- ✅ Works with ANY bank format (no parser maintenance)
- ✅ Leverages Claude Code subscription (no API costs)
- ✅ User can verify extraction accuracy before importing
- ✅ Simpler codebase (no PDF parsing libraries needed)
- ✅ No Java/conda dependency for tabula-py

**Example Usage:**
```bash
/extract-statement statements/maybank/
/extract-statement statements/uob/
```

## Key Architectural Decisions

### Why No MCC Codes?
Credit card statements (Maybank, UOB, DBS) **do not include MCC codes** in the PDF output - only merchant names and locations. Therefore, categorization must rely on:
- Keyword matching on merchant names
- User-maintained blacklist categories
- Manual review for ambiguous cases

### Why Blacklist Instead of ML?
1. **User books flights/tours for both self and parents** - Same merchant can belong to different people depending on context
2. **ML would have high false positive rate** - Cannot reliably distinguish "Jetstar flight for me" vs "Jetstar flight for parents" based on merchant name alone
3. **Blacklist provides explicit control** - User decides which categories require manual review
4. **Simpler and more transparent** - No training data needed, no model drift, easy to understand and debug
5. **User can adapt on the fly** - Add new blacklist categories as patterns emerge

### Why Auto-Create "Self" Person?
Cards not in YAML belong to the user by default. Auto-creating a "self" person:
- Avoids requiring user to list their own cards in YAML (privacy)
- Provides catch-all for new/unknown cards
- Simplifies onboarding (only need to list family members' cards)

## Dependencies

```txt
# Core
fastapi==0.109.0
uvicorn[standard]==0.27.0
python-telegram-bot==20.7
sqlalchemy==2.0.25
alembic==1.13.1

# Database
psycopg2-binary==2.9.9

# PDF Extraction: Manual via Claude Code custom slash command
# No automated parsing dependencies needed

# Utilities
python-dotenv==1.0.0
pydantic==2.5.3
pydantic-settings==2.1.0
pyyaml==6.0.1

# Testing
pytest==7.4.4
pytest-asyncio==0.23.3
```

**Note:** ML dependencies (scikit-learn, numpy, joblib) removed from original plan.

## Success Criteria

**MVP Complete When:**
- ✅ 100% of YAML-listed cards auto-assigned correctly (card-direct rules)
- ✅ 100% of non-YAML cards assigned to "self"
- ✅ 100% of blacklist-matched transactions trigger manual review (zero false negatives)
- ✅ 95%+ of refunds auto-matched to original transactions
- ✅ Can generate accurate bills for all persons (from YAML + "self")
- ✅ Bills include both statement transactions AND manual recurring bills
- ✅ User can dynamically add blacklist categories via Telegram
- ✅ End-to-end workflow (<5 min from upload to bill) works smoothly
- ✅ Deployed to cloud and accessible 24/7 via Telegram
- ✅ Zero incorrect auto-assignments (blacklist ensures manual review for ambiguous cases)

## Next Steps

1. Create Alembic migration for blacklist_categories and manual_bills tables
2. Implement BlacklistMatcher service
3. Update TransactionCategorizer to use blacklist matching
4. Implement Telegram review workflow with inline buttons
5. Test with existing statements

For detailed implementation examples, see the full plan in `.claude/plans/twinkly-sleeping-wreath.md`
