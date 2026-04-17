# Quick Start Guide

Get your expense tracker running in 5 minutes!

## Prerequisites

- Python 3.10 or higher
- Telegram account
- 5 minutes of your time

## Step 1: Get a Telegram Bot Token (2 minutes)

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow the prompts to create your bot
4. Copy the token (looks like: `123456789:ABCdefGhIjKlmNoPQRsTUVwxyZ`)

## Step 2: Install & Configure (2 minutes)

```bash
# Clone or download the repository
cd expense/backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env

# Edit .env and paste your bot token
# TELEGRAM_BOT_TOKEN=your_token_here
```

`backend/.env` is the only supported local runtime env file. Do not create a repo-root `.env`.

## Step 3: Set Up Database (1 minute)

```bash
# Run the interactive setup script
python setup_database.py
```

Follow the prompts to add:
- Parent's name and card number
- Spouse's name and card number
- Your name and card number

Example:
```
1. Parent/Guardian:
  Name: Dad
  Card last 4 digits: 1234

2. Spouse:
  Name: Mom
  Card last 4 digits: 5678

3. Self:
  Name: John
  Card last 4 digits: 9999
```

## Step 4: Start the Bot (30 seconds)

```bash
# Run the bot
python run.py
```

You should see:
```
Starting Expense Tracker Bot
================================================
Host: 0.0.0.0
Port: 8000
...
```

## Step 5: Test It! (30 seconds)

1. Open Telegram
2. Search for your bot (the name you gave it in Step 1)
3. Send `/start`
4. You should see a welcome message!
5. Try `/help` to see all commands
6. Try `/add_expense` to add an ad hoc bill item
7. Try `/alerts` to review pending card-fee or high-value alerts, including the configured card owner name when available

## Next Steps

### Extract Your First Statement

1. Put your PDF statement in the correct `statements/YYYY/MM/bank/` folder
2. Extract transactions into JSON using your preferred workflow:
   - Claude Code: run `/extract-statement`
   - Codex/manual: follow the shared extraction rules in `REPOSITORY_GUIDE.md` and the parsing references under `.claude/commands/`
3. Import the extracted JSON data into the database
4. If you corrected an existing JSON file, refresh it from the repo root with `python .codex/skills/expense-refresh-statement-db/scripts/refresh_statement_db.py <json-path>`
5. Review any uncertain transactions using the Telegram bot buttons
6. Review pending alerts with `/alerts`
7. Before committing DB-only review or billing state, run `cd backend && python export_live_state.py`

### View Statistics

Send `/stats` to see spending breakdown by person

### Generate Bills (Coming in Phase 4)

Send `/bill march parent` to generate a bill for March

### Add or Remove Manual Bill Items

- Use `/add_expense` to create an ad hoc expense for a person and billing month.
- Telegram-added items show up under `Manually Added:` in `/bill`.
- Draft bills include inline remove buttons for those manually added items.
- Seeded recurring charges still show up under `Monthly Recurring:` and are not removable from the bill message.

## Troubleshooting

### "Command not found: alembic"
Just run `python setup_database.py` - it handles database creation automatically.

### "No module named 'app'"
Make sure you're in the `backend` directory and your virtual environment is activated.

### Bot not responding
1. Check your bot token in `backend/.env`
2. Make sure `run.py` is running
3. Check the console for error messages

### PDF extraction
Use the shared statement-extraction workflow to extract transactions from PDF statements. Claude Code can use `/extract-statement`; Codex and manual workflows should follow `REPOSITORY_GUIDE.md` and the parsing references under `.claude/commands/`.

### UOB credit-card credits
Do not skip non-payment UOB `... CR` rows. Merchant refunds, dispute credits, and fee waivers must be extracted as transactions; only payment lines are skipped, and cashback reward lines stay rewards instead of refunds.

### Account high-value alerts
For account-style statements, only `transaction_type = debit` rows should create `high_value` alerts. Credits such as funds transfers or interest should never appear in `/alerts` just because they exceed `$111`.

### Linked refunds
Matched refunds follow the current assignment on their original charge. If you reassign the original later, the linked refund moves with it automatically, including shared splits. If you undo the original back into review, the linked refund becomes non-billable and shows up in `/refund` until the original is reviewed again.

## Advanced: Docker Deployment

```bash
# Build the image
cd backend
docker build -t expense-tracker .

# Run the container
docker run -d \
  --name expense-tracker \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -p 8000:8000 \
  expense-tracker
```

## Tips

1. **Card Numbers**: Use the last 4 digits from your credit card
2. **Multiple Cards**: You can add multiple card numbers per person (comma-separated during setup)
3. **Rules**: The setup script automatically creates smart rules based on your card numbers
4. **Learning**: The bot will learn from your manual assignments over time (Phase 3 feature)

## What's Next?

- Phase 2: Multi-bank support, refund matching
- Phase 3: Machine learning categorization
- Phase 4: Bill generation and formatting

## Need Help?

- Check `README.md` for detailed documentation
- See `plan.md` for the complete implementation plan
- Review `PHASE1_COMPLETE.md` for what's implemented

---

**You're all set! Start uploading statements and let the bot handle your expense tracking.** 🎉
