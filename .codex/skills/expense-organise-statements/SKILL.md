---
name: expense-organise-statements
description: Organise uncategorised statement PDFs from the root `statements/` folder into this repo's `statements/YYYY/MM/bank/` structure. Use when Codex needs to detect bank/month metadata, rename Maybank or UOB files, or move statement PDFs into the correct project folders.
---

# Expense Organise Statements

Use this skill for this repository's statement-file organization workflow.

## Quick Start

1. Read `references/workflow.md`.
2. Only process PDFs that are directly inside the root `statements/` folder.
3. Keep `statements/test/` untouched.

## Rules

- Treat this skill as the Codex-native version of `.claude/commands/organise-statements.md`.
- If this skill and `.claude/commands/organise-statements.md` diverge, follow the Claude command doc for the immediate task and note the mismatch.
- Never recurse into existing year/month/bank subfolders.
- Warn before overwriting an existing destination file.
- Skip unreadable or unidentified PDFs instead of guessing.
