# Statement DB Refresh Workflow

Use this workflow after correcting, re-extracting, or replacing existing statement JSON files.

## Mandatory Rule

- Correcting an existing statement JSON is not finished until the database is updated through `$expense-refresh-statement-db`.
- This is the default repo workflow across all banks.
- Do not run ad hoc `import_statements.py` directly for corrected existing statement files.

## DB Targeting

- Treat `backend/.env` as the source of truth for the intended application DB.
- The intended local DB is `backend/expense_tracker.db`.
- Treat the repo-root `.env` as a hazard for statement DB work because it points to `./expense_tracker.db`.
- The helper script must resolve the backend DB path and report it before importing.

## File Classification

For each explicit JSON path:

- If a matching statement already exists in the backend DB for:
  - `bank_name`
  - `card_last_4` or `account_number_last_4`
  - `statement_date`
  - `billing_month`
  then import it with `--refresh`.
- If those corrected identity fields no longer match because the old imported row was wrong, fall back to the previously imported `raw_file_path` and then to a unique `filename + billing_month` match.
- If no matching statement exists, treat it as a genuinely new statement instance and import it normally.
- Do not use filename suffix alone to decide this. `_2.json` can be either a new statement instance or a mistaken duplicate name, so classification must come from DB presence plus statement identity.
- If fallback matching is ambiguous, stop with an error instead of importing.

## Execution

- Run the helper with explicit JSON file paths only.
- The helper should invoke `backend/import_statements.py` from `backend/`:
  - `--refresh` for corrected existing statements
  - normal import for genuinely new statements
- `--refresh` replaces the imported DB rows for that statement identity. It does not patch one transaction row or one field in place.
- Capture and report:
  - exact refresh file list
  - exact normal import file list
  - per-file outcome
  - post-run duplicate check result for the targeted identities

## Optional Cleanup

- If an accidental repo-root import happened, use `--cleanup-root-db`.
- Cleanup should delete only the targeted statement identities from the repo-root DB and leave unrelated rows untouched.
- Before deleting targeted statement rows from the repo-root DB, cleanup must clear dependent references that point at those old transaction IDs.
