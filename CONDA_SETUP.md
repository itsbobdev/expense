# Conda Environment Setup

## Quick Setup (Recommended)

### Option 1: Using environment.yml (Easiest)

```bash
# Create environment from file
conda env create -f environment.yml

# Activate environment
conda activate expense

# Verify installation
python --version  # Should show Python 3.11.x
```

**That's it!** Skip to [Verify Installation](#verify-installation) below.

---

### Option 2: Manual Setup

If you prefer to create the environment manually:

```bash
# Create new environment with Python 3.11
conda create -n expense python=3.11 -y

# Activate environment
conda activate expense

# Install pip dependencies
cd backend
pip install -r requirements.txt
```

---

## Verify Installation

After setup, verify everything is installed:

```bash
# Make sure environment is activated
conda activate expense

# Check Python version
python --version
# Expected: Python 3.11.x

# Check key packages
python -c "import fastapi; print(f'FastAPI: {fastapi.__version__}')"
python -c "import telegram; print(f'python-telegram-bot: {telegram.__version__}')"

# All should print version numbers without errors
```

---

## Usage

### Activate Environment

**Every time** you work on this project:

```bash
conda activate expense
```

You should see `(expense)` in your terminal prompt.

### Deactivate Environment

When you're done:

```bash
conda deactivate
```

---

## Quick Start After Setup

Once your environment is activated:

```bash
# Configure bot token
cd backend
copy ..\.env.example .env
# Edit .env and add TELEGRAM_BOT_TOKEN

# Set up database
python setup_database.py

# Run the bot
python run.py
```

---

## Troubleshooting

### "conda: command not found"

**Issue:** Conda is not installed

**Solutions:**
1. Install Miniconda: https://docs.conda.io/en/latest/miniconda.html
2. Or install Anaconda: https://www.anaconda.com/download
3. Restart terminal after installation

### "No module named 'fastapi'" after activation

**Issue:** Pip packages not installed

**Solutions:**
```bash
conda activate expense
cd backend
pip install -r requirements.txt
```

### Environment already exists

**Issue:** Want to recreate environment

**Solutions:**
```bash
# Remove existing environment
conda env remove -n expense

# Create new one
conda env create -f environment.yml
```

---

## Managing the Environment

### List all conda environments

```bash
conda env list
```

### Export updated environment

If you install additional packages:

```bash
conda activate expense
conda env export > environment.yml
```

### Update environment from file

If someone else updates `environment.yml`:

```bash
conda activate expense
conda env update -f environment.yml --prune
```

---

## IDE Integration

### VS Code

1. Install Python extension
2. Press `Ctrl+Shift+P` → "Python: Select Interpreter"
3. Choose `expense` (Python 3.11)

### PyCharm

1. File → Settings → Project → Python Interpreter
2. Click gear icon → Add
3. Select "Conda Environment"
4. Choose existing environment: `expense`

### Jupyter Notebook (Optional)

```bash
conda activate expense
conda install jupyter -y
jupyter notebook
```

---

## Why Conda?

**Advantages over pip/venv:**
- ✅ Manages both Python packages AND system dependencies
- ✅ Better dependency resolution
- ✅ Isolated environments that don't interfere with system Python
- ✅ Easy to recreate exact environment on different machines
- ✅ Works consistently on Windows, Mac, and Linux

**For this project:**
- ✅ Handles binary dependencies better than pip
- ✅ Easier to manage Python version (3.11)

---

## Environment File Structure

The `environment.yml` includes:

```yaml
name: expense                   # Environment name
channels:                       # Where to get packages
  - conda-forge                 # Community packages
  - defaults                    # Official Anaconda packages
dependencies:
  - python=3.11                 # Python version
  - pip                         # Pip package manager
  - pip:                        # Pip-only packages
    - fastapi==0.109.0
    - python-telegram-bot==20.7
    # ... all other packages
```

---

## Common Commands Cheat Sheet

```bash
# Create environment
conda env create -f environment.yml

# Activate
conda activate expense

# Deactivate
conda deactivate

# List environments
conda env list

# Remove environment
conda env remove -n expense

# Update environment
conda env update -f environment.yml --prune

# Export environment
conda env export > environment.yml

# List packages in environment
conda list

# Search for package
conda search package-name

# Install additional package
conda install package-name
# or
pip install package-name
```

---

## Alternative: Minimal Setup (pip + venv)

If you prefer NOT to use conda:

```bash
# Create virtual environment
python -m venv venv

# Activate
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

```

---

## Next Steps

After environment setup:

1. ✅ Environment created and activated
2. ✅ All dependencies installed

**Now you can:**
- Follow **START_HERE.md** for quick start
- Run `python backend/run.py` to start the bot

---

## Getting Help

**Environment issues?**
- Check conda is installed: `conda --version`
- Check environment exists: `conda env list`
- Check environment is activated: Look for `(expense)` in prompt

**Package issues?**
- Verify installation: `conda list | grep package-name`
- Reinstall: `pip install --force-reinstall package-name`

---

**Environment ready? Start with: `python backend/run.py`** 🚀
