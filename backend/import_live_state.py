"""
Import a git-tracked live-state snapshot into the current database.

Usage:
    cd backend && python import_live_state.py
    cd backend && python import_live_state.py --input ../state/live_state.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal
from live_state import import_live_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Import live DB state from a JSON snapshot.")
    parser.add_argument(
        "--input",
        default=str(Path(__file__).resolve().parents[1] / "state" / "live_state.json"),
        help="Input JSON path. Defaults to ../state/live_state.json",
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SystemExit(f"Not found: {input_path}")

    db = SessionLocal()
    try:
        result = import_live_state(db, input_path)
        print(f"Imported live state from {input_path}")
        print(
            f"Transactions: {result['transactions']} | "
            f"Manual bills: {result['manual_bills']} | "
            f"Bills: {result['bills']}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
