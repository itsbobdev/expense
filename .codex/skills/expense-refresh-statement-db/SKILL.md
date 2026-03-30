---
name: expense-refresh-statement-db
description: Safely update the statement database after correcting or re-extracting existing statement JSON files. Use whenever an existing statement JSON is fixed and replaced so Codex refreshes the backend DB instead of doing a normal ad hoc import.
---

# Expense Refresh Statement DB

Use this skill whenever an existing statement JSON has been corrected, re-extracted, or replaced.

## Mandatory Trigger

- If Codex finds a mistake in an existing statement JSON and rewrites that JSON, Codex must use `$expense-refresh-statement-db` to update the DB.
- Do not use a direct ad hoc `python import_statements.py ...` call for corrected existing statement JSON files.
- If the file is a genuinely new statement instance that does not already exist in the DB, this skill still owns the classification and normal import step.

## Quick Start

1. Read `references/workflow.md`.
2. Run the helper script with the explicit JSON paths that were corrected or added.
3. Report the exact refresh file list, exact normal import file list, and the per-file outcome.

## Command

```powershell
python .codex/skills/expense-refresh-statement-db/scripts/refresh_statement_db.py `
  statements/2025/10/uob/example.json `
  statements/2025/10/uob/example_2.json
```

Use `--cleanup-root-db` only when an accidental repo-root import needs to be cleaned up.

```powershell
python .codex/skills/expense-refresh-statement-db/scripts/refresh_statement_db.py `
  --cleanup-root-db `
  statements/2025/10/uob/example.json
```

## Notes

- The helper resolves the repo root automatically and always targets `backend/.env` for the intended app DB.
- The helper decides `--refresh` versus normal import by checking the existing DB identity first, then falling back to the previously imported statement path or a unique filename match for the same billing month.
- Refresh is statement-file scoped: it replaces the imported DB rows for that statement identity instead of patching individual transaction rows in place.
- Distinct `_2.json` files still go through this skill; the helper decides whether they are new imports or refreshes.
- The helper currently supports SQLite DB targets only.
- If fallback matching is ambiguous, the helper fails instead of guessing.
- `--cleanup-root-db` is a narrow recovery tool for accidental repo-root imports. It should be used sparingly because it removes targeted statement rows from the repo-root DB after clearing dependent references there.
