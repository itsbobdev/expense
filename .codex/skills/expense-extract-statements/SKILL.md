---
name: expense-extract-statements
description: Extract structured statement JSON for this repo from bank statement PDFs under `statements/YYYY/MM/bank/`. Use when Codex needs to process Citi, HSBC, Maybank, or UOB statement PDFs, save adjacent JSON files, append rewards history, or follow this repo's statement extraction/output rules.
---

# Expense Extract Statements

Use this skill for this repository's manual statement extraction workflow.

## Quick Start

1. Read `references/workflow.md`.
2. Read `references/categories.md`.
3. Read the bank-specific guide under `references/banks/` for the folder or PDF being processed.
4. Follow the exact JSON/output contract from the references.

## Rules

- Treat this skill as the Codex-native version of the repo's Claude extraction command.
- The canonical upstream rules still live in `.claude/commands/`.
- If this skill and `.claude/commands/` ever differ, follow `.claude/commands/` for the immediate task and note that the skill needs syncing.
- Keep the workflow repo-specific:
  - input PDFs live under `statements/YYYY/MM/bank/`
  - extracted JSON files are saved alongside the PDFs
  - rewards summary entries are appended to `statements/rewards_history.json`
  - person/card lookup comes from `statements/statement_people_identifier.yaml`

## Execution Notes

- Process every PDF in the requested folder unless the user narrows the scope.
- For image-based HSBC statements, render page images first with `backend/render_statement_pages.py`, then read those images visually rather than assuming extractable text.
- For HSBC rewards extraction, inspect the `Rewards Summary` section visually from the rendered page images and append the normalized summary entry to `statements/rewards_history.json`.
- Preserve all required fields, null behavior, refund handling, reward handling, and filename conventions from the references.
- Apply all matching categories, not just the first one.
- If an existing extracted JSON is corrected or replaced, follow the DB update with `$expense-refresh-statement-db` instead of a direct ad hoc importer call.
