@echo off
echo ========================================
echo Activating Expense Tracker Environment
echo ========================================
echo.

call conda activate expense

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Failed to activate environment
    echo.
    echo Please run: conda env create -f environment.yml
    pause
    exit /b 1
)

echo.
echo Environment activated: expense
echo Python version:
python --version

echo.
echo Java version:
java -version 2>&1 | findstr /C:"openjdk version"

echo.
echo ========================================
echo Ready to run the bot!
echo ========================================
echo.
echo Next steps:
echo   1. Configure: cd backend ^&^& copy ..\.env.example .env
echo   2. Setup DB:  python setup_database.py
echo   3. Run bot:   python run.py
echo.
