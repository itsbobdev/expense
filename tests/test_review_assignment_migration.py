import os
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


def test_alembic_upgrade_adds_review_origin_and_transaction_splits(tmp_path):
    db_path = tmp_path / "migration.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES ('006')")
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
            INSERT INTO transactions (assignment_method, needs_review)
            VALUES ('category_review', 1)
            """
        )
        conn.commit()

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["TELEGRAM_BOT_TOKEN"] = "test-token"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "007"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(transactions)").fetchall()
        }
        assert "review_origin_method" in columns

        split_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(transaction_splits)").fetchall()
        }
        assert {
            "id",
            "transaction_id",
            "person_id",
            "split_amount",
            "split_percent",
            "sort_order",
        }.issubset(split_columns)

        review_origin_method = conn.execute(
            "SELECT review_origin_method FROM transactions WHERE id = 1"
        ).fetchone()[0]
        assert review_origin_method == "category_review"
