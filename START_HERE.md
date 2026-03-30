# ⚡ Quick Start - 5 Minutes to Running Bot

Follow these steps **exactly** to get your bot running in 5 minutes.

## Step 1: Get Telegram Bot Token (2 minutes)

1. Open Telegram
2. Search for `@BotFather`
3. Send: `/newbot`
4. Enter bot name: `My Expense Tracker`
5. Enter username: `cj_expense_tracker_bot` (must end with "_bot")
6. **Copy the token** that BotFather sends (looks like `123456789:ABCdefGhi...`)

## Step 2: Install Dependencies (1 minute)

Open terminal in the `expense` directory:

```bash
cd backend
pip install -r requirements.txt
```

Wait for installation to complete...

## Step 3: Configure Bot Token (30 seconds)

**Windows:**
```bash
copy ..\\.env.example .env
notepad .env
```

**Mac/Linux:**
```bash
cp ../.env.example .env
nano .env
```

**Edit the file to add your token:**
```
TELEGRAM_BOT_TOKEN=paste_your_token_here
DATABASE_URL=sqlite:///./expense_tracker.db
DEBUG=True
```

Save and close.

## Step 4: Set Up Database (1 minute)

```bash
python setup_database.py
```

**Enter your family details:**
```
1. Parent/Guardian:
  Name: Dad
  Card last 4 digits: 0104

2. Spouse:
  Name: Mom
  Card last 4 digits: 7857

3. Self:
  Name: Your Name
  Card last 4 digits: 7067
```

*(Use the last 4 digits from the example statements if you want to test immediately)*

## Step 5: Start the Bot (30 seconds)

```bash
python run.py
```

You should see:
```
============================================================
Starting Expense Tracker Bot
============================================================
...
INFO:     Application startup complete.
```

**✅ Bot is running!**

## Step 6: Test in Telegram (30 seconds)

1. Open Telegram
2. Search for your bot: `@my_expense_tracker_bot`
3. Send: `/start`

You should see the welcome message! 🎉

## Step 7: Extract a Statement

Extract transactions from your PDF statements (supports Citi, Maybank, UOB), then import the JSON data into the database.

- Claude Code: use `/extract-statement`
- Codex/manual workflow: follow `REPOSITORY_GUIDE.md` and use `.claude/commands/` as parsing and output-reference docs

---

## 🎯 You're Done!

Your expense tracker is now running. Try:

- `/stats` - See spending breakdown
- `/help` - See all commands

## 🚨 Troubleshooting

**Bot doesn't respond?**
- Check the token in `.env` is correct
- Make sure `python run.py` is still running

**Missing dependencies?**
- Run: `pip install -r requirements.txt` again

**Need help?**
- Check `DEPLOYMENT_GUIDE.md` for detailed instructions
- Check `TEST_CHECKLIST.md` for comprehensive testing

---

## 🚀 Next Steps

1. **Extract statements** using the shared extraction workflow
   - Claude Code shortcut: `/extract-statement`
   - Codex/manual path: follow `REPOSITORY_GUIDE.md`
2. **Review and assign** transactions using the buttons
3. **Check stats** with `/stats` command
4. **Deploy to cloud** (see `DEPLOYMENT_GUIDE.md`)

**Enjoy tracking your expenses! 💰📊**
