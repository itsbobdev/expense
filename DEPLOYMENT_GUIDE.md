# Deployment & Testing Guide

## Quick Start (5 Minutes)

### 1. Get a Telegram Bot Token

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow prompts:
   - Bot name: "My Expense Tracker" (or any name)
   - Username: "myexpensetracker_bot" (must end with "bot")
4. Copy the token (format: `123456789:ABCdefGhIjKlmNoPQRsTUVwxyZ`)

### 2. Install Dependencies

```bash
# Navigate to backend directory
cd backend

# Create virtual environment (optional but recommended)
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Create .env file from template
cp ../.env.example .env

# Edit .env file and add your bot token
# TELEGRAM_BOT_TOKEN=your_token_from_botfather
```

**On Windows, edit `.env` with Notepad:**
```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIjKlmNoPQRsTUVwxyZ
DATABASE_URL=sqlite:///./expense_tracker.db
DEBUG=True
```

### 4. Set Up Database

```bash
# Run the interactive setup script
python setup_database.py
```

**Example interaction:**
```
1. Parent/Guardian:
  Name: Dad
  Card last 4 digits: 0104

2. Spouse:
  Name: Mom
  Card last 4 digits: 7857

3. Self:
  Name: John
  Card last 4 digits: 7067
```

### 5. Run the Bot

```bash
# Start the bot
python run.py
```

You should see:
```
============================================================
Starting Expense Tracker Bot
============================================================

Host: 0.0.0.0
Port: 8000
Debug: True
Database: sqlite:///./expense_tracker.db

Press Ctrl+C to stop the server
============================================================

INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### 6. Test in Telegram

1. Open Telegram
2. Search for your bot by username (e.g., `@myexpensetracker_bot`)
3. Send `/start` command
4. You should see the welcome message!

---

## Testing the Bot

### Test Full Workflow

1. **Send `/start` to bot** - Verify welcome message appears

2. **Extract transactions** - Use the shared statement-extraction workflow on your PDF statements
   - Claude Code: `/extract-statement`
   - Codex/manual: follow `REPOSITORY_GUIDE.md` and the parsing references under `.claude/commands/`

3. **Import transactions** - Import the extracted JSON into the database

4. **Review transactions** - If any need review, you'll see buttons:
   ```
   🤔 Transaction Review

   📅 Date: 2026-01-09
   🏪 Merchant: SERAYA ENERGY PTE LTD
   💰 Amount: $40.74

   Who should pay for this?
   [Parent] [Spouse] [Self] [Skip]
   ```

5. **Test `/stats` command** - View spending by person

---

## Troubleshooting

### Bot Not Responding

**Issue:** Bot doesn't reply to commands

**Solutions:**
1. Check bot token is correct in `.env`
2. Verify `run.py` is running (should see "Application startup complete")
3. Check console for errors
4. Make sure you're messaging the correct bot

### Database Errors

**Issue:** "No such table" or database errors

**Solutions:**
```bash
# Reinitialize database
cd backend
rm expense_tracker.db  # Delete old database
python setup_database.py  # Run setup again
```

### Import Errors

**Issue:** "ModuleNotFoundError"

**Solutions:**
```bash
# Make sure you're in backend directory
cd backend

# Reinstall dependencies
pip install -r requirements.txt

# Check virtual environment is activated
# You should see (venv) in your prompt
```

---

## Cloud Deployment

### Option 1: Railway (Recommended)

**Why Railway?**
- Free tier: $5/month credit
- Automatic deployments from GitHub
- Built-in PostgreSQL
- Easy setup

**Steps:**

1. **Push code to GitHub:**
   ```bash
   git add .
   git commit -m "Add expense tracker bot"
   git push origin main
   ```

2. **Deploy to Railway:**
   - Go to https://railway.app
   - Sign up with GitHub
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your repository
   - Click "Add PostgreSQL" service
   - Add environment variables:
     ```
     TELEGRAM_BOT_TOKEN=your_token
     DATABASE_URL=${{Postgres.DATABASE_URL}}
     ```

3. **Initialize Database:**
   - Wait for deployment
   - Go to Railway dashboard
   - Click on your service
   - Click "Shell" tab
   - Run: `python setup_database.py`

4. **Test:**
   - Your bot is now running 24/7!
   - Message it on Telegram

### Option 2: Render

**Steps:**

1. **Create account:** https://render.com

2. **Create new Web Service:**
   - Connect GitHub repository
   - Select "Python 3" environment
   - Build command: `pip install -r backend/requirements.txt`
   - Start command: `cd backend && python run.py`

3. **Add PostgreSQL:**
   - Click "New PostgreSQL"
   - Note the connection string

4. **Environment variables:**
   ```
   TELEGRAM_BOT_TOKEN=your_token
   DATABASE_URL=postgres://...
   ```

5. **Deploy and test**

### Option 3: Docker (Any Platform)

**Build and run locally:**
```bash
# Build image
cd backend
docker build -t expense-tracker .

# Run container
docker run -d \
  --name expense-bot \
  -p 8000:8000 \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e DATABASE_URL=sqlite:///./expense_tracker.db \
  expense-tracker
```

**Deploy to any cloud:**
- Push image to Docker Hub
- Deploy to AWS ECS, Google Cloud Run, Azure, etc.

---

## Production Checklist

Before going to production:

- [ ] Set `DEBUG=False` in `.env`
- [ ] Use PostgreSQL instead of SQLite
- [ ] Set up automated database backups
- [ ] Configure error monitoring (e.g., Sentry)
- [ ] Test with all family members
- [ ] Upload real statements and verify accuracy
- [ ] Set up assignment rules for all cards
- [ ] Test refund handling
- [ ] Test bill generation
- [ ] Document your specific rules and setup

---

## Quick Reference

### Common Commands

```bash
# Start bot locally
cd backend && python run.py

# Reset database
rm backend/expense_tracker.db
cd backend && python setup_database.py

# Check logs
# Logs appear in console where run.py is running

# Stop bot
# Press Ctrl+C in terminal
```

### Telegram Bot Commands

```
/start - Welcome message
/help - Show help
/upload - Upload statement PDF
/stats - View spending statistics
/bill [month] [person] - Generate bill (Phase 4)
```

### File Locations

```
backend/
  expense_tracker.db        # Database file
  uploads/                  # Uploaded PDFs
  ml_models/               # ML models (Phase 3)
  run.py                   # Start script
  setup_database.py        # Database setup
```

---

## Next Steps

Once everything is working:

1. **Upload all your statements** - Test with real data
2. **Review assignments** - Make sure rules are working correctly
3. **Train the ML model** - Manual assignments help ML learn (Phase 3)
4. **Generate bills** - Coming in Phase 4
5. **Set up automated backups** - Protect your data
6. **Deploy to cloud** - For 24/7 access

---

## Getting Help

**Issues?**
- Check console logs for detailed error messages
- Review troubleshooting section above
- Check `README.md` for more details
- Review `plan.md` for architecture details

**Working?**
- ✅ You're ready to track expenses!
- Try uploading different statements
- Test the review workflow
- Explore the categorization rules

---

**Happy Expense Tracking! 🎉**
