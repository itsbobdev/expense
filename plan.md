# Expense Tracking & Billing System - Implementation Plan

## Overview

Build a **Telegram bot-based expense tracker** to automatically bill parents and spouse based on credit card statements. The system will parse PDF statements, categorize transactions using rules + ML, handle refunds, and generate monthly bills.

## User Requirements Summary

**Input:** Credit card statements (PDF format)
**Output:** Bills for parents and spouse via Telegram
**Platform:** Telegram bot (mobile-first, cloud-hosted)
**Timeline:** 2-3 weeks for MVP

### Business Logic Scenarios

1. **Easy:** Supplementary cards → Direct billing (card 1234 → parent)
2. **Easy:** Spouse's card used by parents → All except bus/MRT go to parents
3. **Hard:** User's main card for parents → ML with **high confidence threshold (95%+)** for auto-assignment, otherwise manual review
4. **Hard:** Merchant refunds → Auto-match to original transaction and assign to same person

## Technology Stack

- **Backend:** FastAPI (Python 3.10+)
- **Bot:** python-telegram-bot
- **Database:** SQLite (MVP) → PostgreSQL (production)
- **PDF Parsing:** pdfplumber + tabula-py
- **ML:** scikit-learn (RandomForest classifier)
- **Deployment:** Railway or Render (cloud hosting, free tier)

## System Architecture

```
┌─────────────────────────────────────┐
│       Telegram Bot Interface        │
│  - Upload PDF statements            │
│  - Review uncertain transactions    │
│  - Generate & view bills            │
│  - Manage rules                     │
└─────────────┬───────────────────────┘
              │ Telegram API
              v
┌─────────────────────────────────────┐
│         FastAPI Backend             │
├─────────────────────────────────────┤
│  StatementParser → TransactionDB    │
│  Categorizer (Rules + ML)           │
│  RefundHandler                      │
│  BillingEngine                      │
└─────────────┬───────────────────────┘
              │
              v
┌─────────────────────────────────────┐
│    SQLite Database                  │
│  - statements, transactions         │
│  - persons, rules, categories       │
│  - bills, ml_training_data          │
└─────────────────────────────────────┘
```

## Database Schema (Core Tables)

**persons** - Family members (parent, spouse, self)
- id, name, relationship, card_last_4_digits[]

**statements** - Uploaded credit card statements
- id, filename, card_last_4, statement_date, status, raw_file_path

**transactions** - Individual transactions from statements
- id, statement_id, date, merchant_name, amount, is_refund
- category, assigned_to_person_id, assignment_confidence, assignment_method
- needs_review (boolean), reviewed_at

**assignment_rules** - Categorization rules
- id, priority, rule_type (card_direct, category, merchant)
- conditions (JSON), assign_to_person_id

**bills** - Generated bills for each person
- id, person_id, period_start, period_end, total_amount, status

**bill_line_items** - Transactions in each bill
- id, bill_id, transaction_id, amount, description

**ml_training_data** - For ML model training
- id, transaction_id, features (JSON), label (person_id)

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1)

**Goal:** Set up project, database, basic bot, simple card assignment

**Tasks:**
1. Initialize FastAPI project structure
2. Set up SQLite database with SQLAlchemy + Alembic migrations
3. Create core models (Person, Statement, Transaction, Rule, Bill)
4. Implement Telegram bot skeleton (commands: /start, /help, /upload)
5. Basic PDF parser for DBS/POSB statements (pdfplumber)
6. Simple card-based assignment rules (Scenario 1)
7. Cloud deployment setup (Railway/Render)

**Deliverables:**
- ✅ Bot can receive /start command
- ✅ Database schema created and migrated
- ✅ Can upload PDF file via Telegram (saves to disk)
- ✅ Basic parsing extracts transactions from DBS PDF
- ✅ Direct card assignment works (card X → person Y)

### Phase 2: Categorization & Review Workflow (Week 2)

**Goal:** Implement all 4 scenarios, manual review system

**Tasks:**
1. **Scenario 2:** Category detection (bus/MRT keywords) + rule priority system
2. **Scenario 3:** Keyword-based heuristics (flights, tours, cleaning services)
3. **Scenario 4:** Refund matching algorithm (find original transaction)
4. Telegram interactive review workflow:
   - Send uncertain transactions as messages with inline buttons
   - Buttons: [👨 Parent] [👫 Spouse] [👤 Self] [❌ Skip]
   - Save manual assignments to ml_training_data table
5. Add multi-bank PDF parsers (OCBC, UOB, Citibank)
6. Error handling and logging

**Deliverables:**
- ✅ Bus/MRT transactions correctly assigned (Scenario 2)
- ✅ Refunds auto-match to original transactions (Scenario 4)
- ✅ Telegram review prompts for uncertain transactions
- ✅ Manual assignments saved for future ML training
- ✅ Support for 3+ bank statement formats

### Phase 3: ML Categorization (Week 2-3)

**Goal:** Smart learning for Scenario 3 with high confidence threshold

**Tasks:**
1. Feature extraction from transactions:
   - Merchant name (TF-IDF)
   - Amount buckets (<50, 50-200, 200-500, 500+)
   - Day of week, month, weekend flag
   - Category keywords (binary vector)
2. Implement ML training pipeline:
   - Train RandomForest after 50+ manual labels
   - Auto-retrain after every 10 new manual reviews
3. **High confidence threshold:** Only auto-assign if confidence >= 95%
   - 95%+ → Auto-assign
   - 50-95% → Show as suggestion in review prompt ("ML guessed: Parent, 78% confidence")
   - <50% → No suggestion, just ask user
4. Model persistence (save/load pickle files)
5. ML accuracy metrics and monitoring

**Deliverables:**
- ✅ ML model trains after 50+ manual assignments
- ✅ Conservative auto-assignment (95%+ confidence only)
- ✅ ML suggestions shown in Telegram review prompts
- ✅ Model retrains automatically as user provides feedback
- ✅ Low false positive rate (<5%)

### Phase 4: Billing & Polish (Week 3)

**Goal:** Generate bills, send via Telegram, final testing

**Tasks:**
1. Billing engine implementation:
   - Generate bill for person + date range
   - Group transactions by person
   - Calculate totals (handle refunds correctly)
2. Telegram bill formatting:
   - Pretty text format with line items
   - Commands: /bill [month] [person]
   - Example: "/bill march parent"
3. Additional commands:
   - /stats - Show statistics (total spent, transactions by person)
   - /rules - View/edit assignment rules
   - /retrain - Manually trigger ML retraining
4. Comprehensive testing:
   - Unit tests (categorizer, refund handler, billing)
   - Integration tests (full workflow)
   - Test with real statements
5. Documentation (README, user guide)
6. Cloud deployment and monitoring

**Deliverables:**
- ✅ Bills generate correctly with all transactions
- ✅ Refunds deducted properly in bills
- ✅ Telegram commands work end-to-end
- ✅ Deployed to Railway/Render with PostgreSQL
- ✅ 90%+ accuracy on test statements

## Critical Files to Create

### Core Backend Files
1. `backend/app/database.py` - SQLAlchemy connection, session management
2. `backend/app/models/transaction.py` - Transaction model (central data structure)
3. `backend/app/models/person.py` - Person model
4. `backend/app/models/statement.py` - Statement model
5. `backend/app/models/rule.py` - AssignmentRule model
6. `backend/app/models/bill.py` - Bill and BillLineItem models

### Service Layer
7. `backend/app/services/parser.py` - StatementParser (PDF → transactions)
8. `backend/app/services/categorizer.py` - TransactionCategorizer (rules + ML)
9. `backend/app/services/ml_categorizer.py` - MLCategorizer (feature extraction, training)
10. `backend/app/services/refund_handler.py` - RefundHandler (match refunds)
11. `backend/app/services/billing_engine.py` - BillingEngine (generate bills)

### Bank Parsers
12. `backend/app/parsers/base.py` - Base parser interface
13. `backend/app/parsers/dbs.py` - DBS/POSB parser
14. `backend/app/parsers/ocbc.py` - OCBC parser (Phase 2)
15. `backend/app/parsers/uob.py` - UOB parser (Phase 2)

### Telegram Bot
16. `backend/app/bot/telegram_bot.py` - Main bot application
17. `backend/app/bot/handlers.py` - Command handlers (/start, /upload, /bill, etc.)
18. `backend/app/bot/keyboards.py` - Inline keyboard layouts

### Configuration & Deployment
19. `backend/app/main.py` - FastAPI app entry point
20. `backend/app/config.py` - Settings (env vars, database URL)
21. `backend/requirements.txt` - Python dependencies
22. `backend/Dockerfile` - Container definition
23. `backend/alembic/versions/001_initial_schema.py` - Database migration
24. `.env.example` - Environment variables template
25. `README.md` - Setup and usage documentation

## Scenario-Specific Solutions

### Scenario 1: Supplementary Cards (Direct Assignment)

**Implementation:**
```python
# Rule in database
{
    "rule_type": "card_direct",
    "priority": 100,
    "conditions": {"card_last_4": "1234"},
    "assign_to_person_id": 2  # parent
}

# In categorizer
if rule := get_card_direct_rule(transaction.card_last_4):
    return Assignment(person=rule.person, confidence=1.0, method='card_direct')
```

**Complexity:** ⭐ (Trivial)

### Scenario 2: Spouse's Card + Category Split

**Implementation:**
```python
# Two rules in priority order
# Rule 1 (priority=100): Card 5678 + Bus/MRT → Spouse
{
    "conditions": {"card_last_4": "5678", "category": ["transport_bus", "transport_mrt"]},
    "assign_to_person_id": 3  # spouse
}

# Rule 2 (priority=50): Card 5678 + Everything else → Parent
{
    "conditions": {"card_last_4": "5678"},
    "assign_to_person_id": 2  # parent
}

# Category detection from merchant name
def detect_transport_category(merchant):
    if any(kw in merchant.lower() for kw in ['sbs', 'smrt bus', 'tower transit']):
        return 'transport_bus'
    if any(kw in merchant.lower() for kw in ['mrt', 'simplygo', 'ez-link']):
        return 'transport_mrt'
    return None
```

**Complexity:** ⭐⭐ (Simple rules)

### Scenario 3: Main Card Smart Categorization

**Implementation Strategy:**

**Step 1:** Keyword heuristics (immediate, no training needed)
```python
PARENT_KEYWORDS = {
    'flights': ['jetstar', 'scoot', 'changi', 'airline', 'airways', 'singapore air'],
    'tours': ['tour', 'klook', 'pelago', 'chan brothers', 'travel agency'],
    'cleaning': ['helper', 'maid', 'cleaning service'],
}

if category := detect_parent_category(merchant_name):
    return Assignment(person='parent', confidence=0.70, method='keyword_heuristic')
```

**Step 2:** ML prediction (after 50+ training examples)
```python
# Features
features = {
    'merchant_tfidf': vectorize(merchant_name),
    'amount_bucket': bucket(amount),  # <50, 50-200, 200-500, >500
    'day_of_week': date.weekday(),
    'is_weekend': date.weekday() >= 5,
    'has_flight_keywords': check_keywords(merchant_name, PARENT_KEYWORDS['flights']),
    'has_tour_keywords': check_keywords(merchant_name, PARENT_KEYWORDS['tours']),
}

# Predict with RandomForest
person_id, confidence = ml_model.predict(features)

# CONSERVATIVE THRESHOLD
if confidence >= 0.95:
    # Very high confidence → auto-assign
    return Assignment(person=person_id, confidence=confidence, method='ml_auto')
elif confidence >= 0.50:
    # Medium confidence → suggest in review prompt
    return Assignment(person=person_id, confidence=confidence, method='ml_suggest', needs_review=True)
else:
    # Low confidence → no suggestion
    return Assignment(person=None, confidence=0.0, needs_review=True)
```

**Telegram Review Workflow:**
```
🤔 Transaction needs review:

📅 Date: 2024-03-15
🏪 Merchant: Changi Airport T3 Transfer
💰 Amount: $458.50

🤖 ML Prediction: Parent (78% confidence)

Who should pay?
[👨 Parent] [👫 Spouse] [👤 Self] [❌ Skip]
```

**Complexity:** ⭐⭐⭐⭐ (ML + training loop + high precision requirement)

### Scenario 4: Merchant Refunds

**Implementation:**
```python
def process_refund(refund_transaction):
    # Step 1: Identify refund (negative amount)
    if refund_transaction.amount >= 0:
        return  # Not a refund

    # Step 2: Find original transaction
    candidates = db.query(Transaction).filter(
        Transaction.merchant_name == refund_transaction.merchant_name,
        Transaction.amount == -refund_transaction.amount,  # Exact match
        Transaction.transaction_date < refund_transaction.transaction_date,
        Transaction.transaction_date >= refund_transaction.transaction_date - timedelta(days=90),
        Transaction.is_refund == False
    ).all()

    if len(candidates) == 1:
        # Exact match found → auto-assign
        original = candidates[0]
        refund_transaction.assigned_to_person_id = original.assigned_to_person_id
        refund_transaction.original_transaction_id = original.id
        refund_transaction.is_refund = True
        refund_transaction.assignment_confidence = 0.95

        # Send notification
        send_telegram_message(
            f"💸 Refund auto-matched!\n"
            f"Original: {original.date} - {original.merchant} - ${original.amount:.2f}\n"
            f"Refund: ${refund_transaction.amount:.2f}\n"
            f"Assigned to: {original.assigned_person.name}"
        )
    else:
        # Ambiguous or no match → needs review
        refund_transaction.needs_review = True
        send_telegram_review_prompt(refund_transaction, candidates)
```

**Edge Cases:**
- Partial refunds (amount mismatch) → needs review
- Multiple matches (multiple bookings same merchant) → needs review
- Old refunds (>90 days) → needs review
- Orphan refunds (no original found) → needs review

**Complexity:** ⭐⭐⭐ (Matching logic + edge cases)

## Key Technologies & Dependencies

```txt
# Core
fastapi==0.109.0
uvicorn[standard]==0.27.0
python-telegram-bot==20.7
sqlalchemy==2.0.25
alembic==1.13.1

# Database
psycopg2-binary==2.9.9  # PostgreSQL (production)

# PDF Parsing
pdfplumber==0.10.3
tabula-py==2.9.0
pandas==2.1.4

# ML
scikit-learn==1.4.0
numpy==1.26.3
joblib==1.3.2

# Utilities
python-dotenv==1.0.0
pydantic==2.5.3
pydantic-settings==2.1.0

# Testing
pytest==7.4.4
pytest-asyncio==0.23.3
```

## Deployment (Railway)

**Setup:**
1. Create Railway account
2. Create new project from GitHub repo
3. Add PostgreSQL database service
4. Set environment variables:
   - `TELEGRAM_BOT_TOKEN` (from BotFather)
   - `DATABASE_URL` (auto-provided by Railway)
   - `PYTHON_VERSION=3.11`
5. Deploy with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

**Cost:** Free tier provides $5 credit/month (sufficient for MVP usage)

## Testing & Verification Plan

### Unit Tests
```python
# Test card assignment
def test_card_direct_assignment():
    categorizer = TransactionCategorizer()
    setup_rule(card="1234", person="parent")

    txn = Transaction(merchant="Test", amount=100, card="1234")
    result = categorizer.categorize(txn)

    assert result.person_name == "parent"
    assert result.confidence == 1.0

# Test bus/MRT detection
def test_transport_category():
    txn = Transaction(merchant="SBS Transit", amount=2.50)
    category = detect_category(txn.merchant)

    assert category == "transport_bus"

# Test refund matching
def test_refund_auto_match():
    original = create_transaction(merchant="Chan Brothers", amount=500, date="2024-01-15")
    refund = create_transaction(merchant="Chan Brothers", amount=-500, date="2024-02-10")

    handler = RefundHandler()
    handler.process_refund(refund)

    assert refund.assigned_to == original.assigned_to
    assert refund.original_transaction_id == original.id
```

### Integration Tests
```python
# Test full workflow
async def test_full_workflow():
    # 1. Upload statement PDF via Telegram
    await bot.send_document(chat_id, file=open('test_statement.pdf'))

    # 2. Verify transactions parsed
    txns = get_transactions()
    assert len(txns) > 0

    # 3. Verify auto-categorization
    auto_assigned = [t for t in txns if not t.needs_review]
    assert len(auto_assigned) > 0

    # 4. Generate bill
    bill = generate_bill(person='parent', month='2024-03')
    assert bill.total > 0
    assert len(bill.line_items) > 0
```

### End-to-End Manual Testing

**Test Case 1: Upload Statement**
1. Send PDF file to bot via Telegram
2. Verify: Bot responds "📄 Processing statement..."
3. Verify: Bot shows "✅ Found X transactions, Y need review"
4. Check database: Statement and transactions created

**Test Case 2: Auto-Categorization (Scenarios 1 & 2)**
1. Upload statement with parent's supplementary card (1234)
2. Verify: All transactions on card 1234 assigned to parent
3. Upload statement with spouse's card (5678)
4. Verify: Bus/MRT → spouse, others → parent

**Test Case 3: Manual Review (Scenario 3)**
1. Upload statement with main card transactions
2. Verify: Bot sends review prompts for uncertain transactions
3. Tap [👨 Parent] button
4. Verify: Transaction assigned to parent
5. Check database: ml_training_data record created

**Test Case 4: ML Auto-Assignment**
1. Manually tag 50+ transactions via Telegram
2. Trigger training: /retrain
3. Upload new statement with similar merchants
4. Verify: High-confidence (95%+) transactions auto-assigned
5. Verify: Medium-confidence (50-95%) shown as suggestions
6. Verify: Low-confidence (<50%) no suggestion

**Test Case 5: Refund Handling (Scenario 4)**
1. Upload statement with tour booking ($500)
2. Upload later statement with refund (-$500, same merchant)
3. Verify: Refund auto-matched to original
4. Verify: Refund assigned to same person as original
5. Verify: Telegram notification sent

**Test Case 6: Bill Generation**
1. Send command: /bill march parent
2. Verify: Bot sends formatted bill with:
   - Correct date range
   - All transactions for parent
   - Correct total (including refunds)
   - Line item details (date, merchant, amount)

**Test Case 7: Edge Cases**
1. Duplicate transactions in statement → handled correctly
2. Ambiguous refund (multiple matches) → prompts for review
3. Unknown bank statement format → error message with instructions
4. PDF parsing failure → fallback to manual entry option

## Success Criteria

**MVP Complete When:**
- ✅ 90%+ of Scenarios 1 & 2 auto-categorized correctly
- ✅ ML achieves 95%+ precision on high-confidence predictions (low false positives)
- ✅ 95%+ of refunds auto-matched to original transactions
- ✅ Can generate accurate bills for 3 family members
- ✅ End-to-end workflow (<5 min from upload to bill) works smoothly
- ✅ Deployed to cloud and accessible 24/7 via Telegram
- ✅ Zero incorrect bills sent (manual review catches all uncertain cases)

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| PDF format changes | Versioned parsers, fallback to manual CSV upload |
| ML false positives | Conservative 95% threshold, always allow manual override |
| Telegram API downtime | Queue messages, retry logic, status monitoring |
| Data loss | Daily automated database backups to cloud storage |
| Wrong bill sent | Draft mode with preview before finalizing |

## Future Enhancements (Post-MVP)

- Progressive Web App (PWA) for rich dashboard and analytics
- Email statement auto-import (forward to bot email)
- Multi-currency support for foreign transactions
- Receipt OCR (photo receipts → auto-add to expenses)
- Budgeting and spending alerts
- Shared access for spouse to review bills
- Bank API integrations for real-time sync
- WhatsApp bot as alternative to Telegram
