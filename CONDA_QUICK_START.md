# Conda Quick Start ⚡

Your conda environment is ready! Here's how to use it.

## ✅ Environment Created

Environment name: **expense**
Location: `C:\Users\backup\anaconda3\envs\expense`

## 🚀 Quick Start

### Method 1: Use the activation script (Windows)

```bash
# Just double-click activate.bat
# Or run in terminal:
activate.bat
```

This will:
- Activate the `expense` environment
- Show Python and Java versions
- Display next steps

### Method 2: Manual activation

```bash
# Activate environment
conda activate expense

# You should see (expense) in your prompt
```

## ▶️ Run the Bot

Once activated:

```bash
# 1. Configure bot token (first time only)
cd backend
copy ..\.env.example .env
notepad .env  # Add your TELEGRAM_BOT_TOKEN

# 2. Set up database (first time only)
python setup_database.py

# 3. Run the bot
python run.py
```

## 📦 What's Installed

The environment includes:
- ✅ Python 3.11
- ✅ FastAPI + Uvicorn
- ✅ python-telegram-bot
- ✅ SQLAlchemy + Alembic
- ✅ pdfplumber + tabula-py
- ✅ scikit-learn (for ML)
- ✅ All other dependencies

## 🔍 Verify Installation

```bash
conda activate expense

# Check Python
python --version
# Expected: Python 3.11.x

# Check packages
python -c "import fastapi; print('FastAPI OK')"
python -c "import telegram; print('Telegram OK')"
```

All should print "OK" without errors.

## 📱 Test in Telegram

1. Make sure bot is running: `python backend/run.py`
2. Open Telegram and search for your bot
3. Send `/start`

## 💡 Daily Usage

**Starting work:**
```bash
conda activate expense
cd backend
python run.py
```

**When done:**
```bash
# Press Ctrl+C to stop bot
conda deactivate
```

## 🔧 Common Tasks

### Update dependencies

```bash
conda activate expense
cd backend
pip install -r requirements.txt
```

### Reinstall environment

```bash
# Remove old environment
conda env remove -n expense

# Create new one
conda env create -f environment.yml
```

### Export environment

```bash
conda activate expense
conda env export > environment-backup.yml
```

## 📚 Full Documentation

- **CONDA_SETUP.md** - Complete conda guide
- **START_HERE.md** - Quick start guide
- **DEPLOYMENT_GUIDE.md** - Deployment options
- **TEST_CHECKLIST.md** - Testing checklist

## ❓ Troubleshooting

### Environment not activating?

```bash
# Check it exists
conda env list

# Should show: expense    C:\Users\backup\anaconda3\envs\expense
```

### "conda: command not found"?

Restart your terminal after installing conda.

### Package not found?

```bash
conda activate expense
pip install package-name
```

## ✨ You're All Set!

Environment is ready. Time to track some expenses! 🎉

**Start the bot:**
```bash
conda activate expense
python backend/run.py
```
