---
name: expense-run-telegram-bot
description: Start, relaunch, or verify the expense tracker Telegram bot for this repository. Use when Codex needs to run the bot quickly for local development, confirm whether the bot is already running, or restart it without re-discovering the repo entrypoint and health-check flow.
---

# Expense Run Telegram Bot

Use the helper script first. It resolves the repo root, checks all live `run.py` processes, checks who owns port `8000`, starts `backend/run.py` in the background, and reports the health result plus log file paths.

Run:

```powershell
python .codex/skills/expense-run-telegram-bot/scripts/start_expense_bot.py
```

Use `--force-restart` when the user explicitly asks to restart the bot, when the existing process is unhealthy, or when the bot seems to be serving stale code.

```powershell
python .codex/skills/expense-run-telegram-bot/scripts/start_expense_bot.py --force-restart
```

## Workflow

1. Run the helper script from the repo root.
2. Read the JSON it prints.
3. Treat `already-running` as valid only when the script reports exactly one `run.py` PID and that PID owns port `8000`.
4. For `--force-restart`, rely on the script to remove the PID file, kill stale `run.py` processes, and kill the process that owns port `8000` before starting a fresh instance.
5. Treat `started` as valid only when the script reports exactly one `run.py` PID and the new PID owns port `8000`.
6. If `status` is `failed`, inspect the log tails it returned and the full files in `backend/bot_stdout.log` and `backend/bot_stderr.log`.
7. If the restart was requested because behavior looked outdated, verify the relevant live code path immediately after restart instead of stopping at a healthy health check.

## Notes

The repo entrypoint is `backend/run.py`. FastAPI startup initializes the database and starts Telegram polling, so there is no separate bot-only command to prefer.

The helper script checks `http://127.0.0.1:8000/health` by default, but health alone is not enough. Success requires one live `run.py` process and that same PID owning port `8000`.

Logs are written to:

- `backend/bot_stdout.log`
- `backend/bot_stderr.log`
- `backend/telegram_bot.pid`

If the user asks to run the bot and does not ask for deeper debugging, prefer this skill over manual repo exploration.
