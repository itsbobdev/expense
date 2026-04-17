import os
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


def test_alembic_upgrade_adds_review_origin_transaction_splits_and_manual_bill_type(tmp_path):
    db_path = tmp_path / "migration.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES ('007')")
        conn.execute("CREATE TABLE persons (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.execute(
            """
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_method TEXT,
                needs_review BOOLEAN
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE manual_bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                amount FLOAT NOT NULL,
                description TEXT NOT NULL,
                billing_month TEXT NOT NULL,
                created_at DATETIME
            )
            """
        )
        conn.execute(
            """
            INSERT INTO transactions (assignment_method, needs_review)
            VALUES ('category_review', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO manual_bills (person_id, amount, description, billing_month)
            VALUES (1, 110.0, 'HDB Season Parking', '2026-03')
            """
        )
        conn.commit()

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["TELEGRAM_BOT_TOKEN"] = "test-token"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "008"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    with sqlite3.connect(db_path) as conn:
        manual_bill_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(manual_bills)").fetchall()
        }
        assert "manual_type" in manual_bill_columns

        manual_type = conn.execute(
            "SELECT manual_type FROM manual_bills WHERE id = 1"
        ).fetchone()[0]
        assert manual_type == "recurring"
