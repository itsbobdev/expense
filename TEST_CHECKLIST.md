# Testing Checklist

Use this checklist to verify everything works correctly.

## ✅ Local Setup

- [ ] Python 3.10+ installed (`python --version`)
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip install -r backend/requirements.txt`)
- [ ] `.env` file created with bot token
- [ ] Database initialized (`python backend/setup_database.py`)

## ✅ Bot Startup

- [ ] Bot starts without errors (`python backend/run.py`)
- [ ] Console shows "Application startup complete"
- [ ] No error messages in console
- [ ] Health check works: http://localhost:8000/health

## ✅ Telegram Bot Commands

### /start Command
- [ ] Bot found in Telegram search
- [ ] `/start` command works
- [ ] Welcome message appears
- [ ] Message includes all available commands

### /help Command
- [ ] `/help` shows help text
- [ ] Lists all commands
- [ ] Lists all commands

### /upload Command
- [ ] `/upload` directs user to use /extract-statement Claude Code command

### /stats Command
- [ ] `/stats` shows spending by person
- [ ] Shows correct totals
- [ ] Handles case when no transactions exist

## ✅ PDF Extraction (via /extract-statement)

- [ ] Run `/extract-statement` on a Citi statement
- [ ] Run `/extract-statement` on a Maybank statement
- [ ] Run `/extract-statement` on a UOB statement
- [ ] Verify JSON output contains correct transaction data
- [ ] Import extracted JSON into the database

## ✅ Transaction Categorization

### Auto-Assignment
- [ ] Transactions with matching card rules are auto-assigned
- [ ] Auto-assigned count shown in summary
- [ ] Check database: `assignment_method` is 'card_direct'
- [ ] Check database: `needs_review` is False for auto-assigned

### Manual Review
- [ ] Uncertain transactions trigger review prompts
- [ ] Review prompt shows date, merchant, amount
- [ ] Shows 4 buttons: Parent, Spouse, Self, Skip
- [ ] Review count shown in summary

### Button Callbacks
- [ ] Click "Parent" button → Transaction assigned to parent
- [ ] Click "Spouse" button → Transaction assigned to spouse
- [ ] Click "Self" button → Transaction assigned to self
- [ ] Click "Skip" button → Transaction marked as skipped
- [ ] Success message appears after assignment
- [ ] Check database: `assignment_method` is 'manual'
- [ ] Check database: `reviewed_at` timestamp set

## ✅ Refund Detection

- [ ] Negative amounts detected as refunds
- [ ] Amounts with 'CR' suffix detected as refunds
- [ ] `is_refund` flag set correctly in database
- [ ] Refunds shown with "(Refund)" label in review prompts

## ✅ Database

### Data Integrity
- [ ] Statements table has records
- [ ] Transactions table has records
- [ ] Persons table has family members
- [ ] Assignment_rules table has rules
- [ ] All foreign keys linked correctly

### Check with SQL
```bash
cd backend
sqlite3 expense_tracker.db

# List all statements
SELECT * FROM statements;

# List all transactions
SELECT id, transaction_date, merchant_name, amount, assigned_to_person_id FROM transactions LIMIT 10;

# List all persons
SELECT * FROM persons;

# List all rules
SELECT * FROM assignment_rules;

# Exit
.quit
```


## ✅ Edge Cases

### Date Handling
- [ ] Transactions from previous year handled correctly
  - Example: December transactions in January statement
- [ ] Dates parsed correctly for all formats

### Special Characters
- [ ] Merchant names with special characters handled
- [ ] Foreign currency symbols handled

## ✅ Error Recovery

- [ ] Bot recovers from database error
- [ ] Bot shows helpful error messages
- [ ] Console logs contain debug information
- [ ] Bot remains responsive after error

## ✅ Performance

- [ ] Bot responds to commands in <3 seconds

## ✅ User Experience

- [ ] Welcome message is clear and helpful
- [ ] Error messages are actionable
- [ ] Success messages confirm what happened
- [ ] Review prompts are easy to understand
- [ ] Stats display is readable
- [ ] All emojis render correctly

## ✅ Cloud Deployment (Optional)

### Railway
- [ ] Project created on Railway
- [ ] GitHub repo connected
- [ ] PostgreSQL database added
- [ ] Environment variables set
- [ ] Deployment successful
- [ ] Bot responds on Telegram
- [ ] Database initialized on Railway
- [ ] Logs accessible

### Docker (Optional)
- [ ] Docker image builds successfully
- [ ] Container runs locally
- [ ] Bot works in container
- [ ] Environment variables passed correctly
- [ ] Volumes mounted for persistent data

## ✅ Production Readiness

- [ ] DEBUG set to False
- [ ] Using PostgreSQL (not SQLite)
- [ ] Database backups configured
- [ ] Error monitoring set up
- [ ] All family members added to database
- [ ] All credit cards added to rules
- [ ] Tested with real statements
- [ ] Rules validated with family

## 🎯 Success Criteria

### Minimum (MVP)
- ✅ Bot starts and responds to commands
- ✅ Can extract and import transactions from bank statements
- ✅ Transactions are categorized (auto or manual)
- ✅ Stats command shows spending breakdown

### Complete (Phase 1 + Multi-Bank)
- ✅ All of the above
- ✅ All example statements extracted successfully
- ✅ Manual review workflow works smoothly
- ✅ Data persists correctly in database
- ✅ Deployed to cloud (optional)

### Ready for Production
- ✅ All of the above
- ✅ Tested with real family statements
- ✅ Rules configured for all family cards
- ✅ Family members can use it successfully
- ✅ Running 24/7 on cloud platform
- ✅ Database backups automated

---

## Quick Test Script

Run this to do a quick smoke test:

```bash
#!/bin/bash

echo "🧪 Running Quick Tests..."

# 1. Check Python
python --version || echo "❌ Python not found"

# 2. Check dependencies
pip freeze | grep -q "fastapi" && echo "✅ Dependencies installed" || echo "❌ Dependencies missing"

# 4. Check database
test -f backend/expense_tracker.db && echo "✅ Database exists" || echo "❌ Database not found"

# 5. Check .env
test -f .env && echo "✅ .env file exists" || echo "❌ .env file missing"

echo ""
echo "✨ Ready to start bot: python backend/run.py"
```

Save as `quick-test.sh` and run: `bash quick-test.sh`

---

**When all boxes are checked, you're ready for production! 🚀**
