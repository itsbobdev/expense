"""
Import statement JSON files into the database.

Usage:
    # Import all JSON files for a billing month (scans statements/YYYY/MM/)
    python import_statements.py 2026-01
    python import_statements.py 2026-01 2026-02 2026-03
    python import_statements.py --refresh 2026-01

    # Import all months found in statements/
    python import_statements.py all

    # Import specific JSON files
    python import_statements.py statements/2026/02/citi/file.json
    python import_statements.py --refresh statements/2026/02/citi/file.json

The JSON files are produced by the /extract-statement command.
The script is idempotent: re-importing the same file is a no-op.
"""
import sys
from pathlib import Path

# Allow running from backend/ or repo root
sys.path.insert(0, str(Path(__file__).parent))

import re
from app.database import SessionLocal, init_db
from app.services.importer import StatementImporter
from app.services.recurring_charges import RecurringChargesService
from app.config import settings


def get_all_months() -> list[str]:
    """Scan statements directory for all YYYY/MM folders."""
    statements_dir = settings.statements_dir
    months = []
    for year_dir in sorted(statements_dir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            months.append(f"{year_dir.name}-{month_dir.name}")
    return months


def import_month(billing_month: str, refresh_existing: bool = False):
    """Import a single billing month and generate recurring charges."""
    year, month = int(billing_month[:4]), int(billing_month[5:7])

    db = SessionLocal()
    try:
        importer = StatementImporter(db)
        result = importer.import_month(year, month, refresh_existing=refresh_existing)

        print(f"\n{'='*50}")
        print(f"  {result.billing_month}")
        print(f"{'='*50}")
        print(f"  Files imported:      {result.files_imported}")
        print(f"  Files skipped:       {result.files_skipped}")
        if result.files_errored:
            print(f"  Files errored:       {result.files_errored}")
        print(f"  Transactions:        {result.total_transactions}")
        print(f"  Flagged for review:  {result.total_flagged}")
        print(f"  Refunds matched:     {result.total_refunds_matched}")

        if result.files_errored:
            print("\n  Errors:")
            for fr in result.file_results:
                if fr.error:
                    print(f"    {fr.filename}: {fr.error}")

        # Generate recurring charges for this month
        recurring = RecurringChargesService(db)
        created = recurring.generate_recurring_bills(billing_month)
        if created:
            print(f"  Recurring charges:   {len(created)}")

        return result

    finally:
        db.close()


def import_files(file_paths: list[str], refresh_existing: bool = False):
    """Import specific JSON files (legacy mode)."""
    db = SessionLocal()
    try:
        importer = StatementImporter(db)
        total_imported = 0
        total_skipped = 0

        for path_str in file_paths:
            json_path = Path(path_str)
            if not json_path.exists():
                print(f"[ERROR] File not found: {json_path}")
                continue

            # Derive billing month from path: .../YYYY/MM/bank/file.json
            billing_month = None
            parts = json_path.parts
            for i, part in enumerate(parts):
                if part.isdigit() and len(part) == 4 and i + 1 < len(parts):
                    next_part = parts[i + 1]
                    if next_part.isdigit() and len(next_part) == 2:
                        billing_month = f"{part}-{next_part}"
                        break

            if not billing_month:
                print(f"[ERROR] Cannot determine billing month from path: {json_path}")
                print(f"  Expected path like: statements/YYYY/MM/bank/file.json")
                continue

            print(f"\nImporting: {json_path}")
            result = importer.import_file(json_path, billing_month, refresh_existing=refresh_existing)

            if result.skipped:
                total_skipped += 1
                print(f"  [SKIP] {result.skip_reason}")
            elif result.error:
                print(f"  [ERROR] {result.error}")
            else:
                total_imported += 1
                print(f"  [OK] {result.transactions_imported} transactions | "
                      f"{result.transactions_flagged} flagged | "
                      f"{result.refunds_auto_matched} refunds matched")

        print(f"\nDone. Imported: {total_imported}, Skipped: {total_skipped}")

    finally:
        db.close()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python import_statements.py [--refresh] YYYY-MM [YYYY-MM ...]")
        print("  python import_statements.py [--refresh] all")
        print("  python import_statements.py [--refresh] path/to/file.json [...]")
        sys.exit(1)

    init_db()

    args = sys.argv[1:]
    refresh_existing = False
    if args and args[0] == "--refresh":
        refresh_existing = True
        args = args[1:]
    if not args:
        print("Usage:")
        print("  python import_statements.py [--refresh] YYYY-MM [YYYY-MM ...]")
        print("  python import_statements.py [--refresh] all")
        print("  python import_statements.py [--refresh] path/to/file.json [...]")
        sys.exit(1)

    # Determine mode: month-based or file-based
    if args[0] == "all":
        months = get_all_months()
        if not months:
            print("No statement folders found.")
            sys.exit(1)
        print(f"Importing {len(months)} months: {', '.join(months)}")
        total_txns = 0
        total_flagged = 0
        for m in months:
            result = import_month(m, refresh_existing=refresh_existing)
            total_txns += result.total_transactions
            total_flagged += result.total_flagged
        print(f"\n{'='*50}")
        print(f"  Done. {total_txns} transactions, {total_flagged} flagged for review.")
        if total_flagged:
            print(f"  Use /review in Telegram bot to assign them.")
        print(f"{'='*50}")

    elif re.match(r'^\d{4}-\d{2}$', args[0]):
        # Month-based import
        months = args
        total_txns = 0
        total_flagged = 0
        for m in months:
            result = import_month(m, refresh_existing=refresh_existing)
            total_txns += result.total_transactions
            total_flagged += result.total_flagged
        print(f"\n{'='*50}")
        print(f"  Done. {total_txns} transactions, {total_flagged} flagged for review.")
        if total_flagged:
            print(f"  Use /review in Telegram bot to assign them.")
        print(f"{'='*50}")

    else:
        # File-based import
        import_files(args, refresh_existing=refresh_existing)


if __name__ == "__main__":
    main()
