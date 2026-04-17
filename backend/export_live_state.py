"""
Export DB-only live state into a git-tracked JSON snapshot.

Usage:
    cd backend && python export_live_state.py
    cd backend && python export_live_state.py --output ../state/live_state.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal
from live_state import export_live_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Export live DB state into a JSON snapshot.")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[1] / "state" / "live_state.json"),
        help="Output JSON path. Defaults to ../state/live_state.json",
    )
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    db = SessionLocal()
    try:
        result = export_live_state(db, output_path)
        print(f"Wrote live state to {output_path}")
        print(
            f"Transactions: {result['transactions']} | "
            f"Manual bills: {result['manual_bills']} | "
            f"Bills: {result['bills']}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
