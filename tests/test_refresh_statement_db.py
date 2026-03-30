import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / ".codex"
    / "skills"
    / "expense-refresh-statement-db"
    / "scripts"
    / "refresh_statement_db.py"
)
SPEC = importlib.util.spec_from_file_location("refresh_statement_db", MODULE_PATH)
refresh_statement_db = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = refresh_statement_db
SPEC.loader.exec_module(refresh_statement_db)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def init_test_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE statements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                bank_name TEXT,
                card_last_4 TEXT NOT NULL,
                statement_date TEXT NOT NULL,
                billing_month TEXT,
                raw_file_path TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL
            )
            """
        )
        conn.commit()


def init_cleanup_test_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE statements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                bank_name TEXT,
                card_last_4 TEXT NOT NULL,
                statement_date TEXT NOT NULL,
                billing_month TEXT,
                raw_file_path TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                original_transaction_id INTEGER,
                parent_transaction_id INTEGER,
                resolved_by_transaction_id INTEGER,
                resolved_method TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE bill_line_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE ml_training_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER
            )
            """
        )
        conn.commit()


def test_classify_existing_statement_as_refresh(tmp_path):
    db_path = tmp_path / "backend.db"
    init_test_db(db_path)
    json_path = tmp_path / "statements" / "2025" / "10" / "uob" / "statement.json"
    write_json(
        json_path,
        {
            "filename": "statement.json",
            "bank_name": "UOB",
            "card_last_4": "4919",
            "statement_date": "2025-10-24",
            "transactions": [],
        },
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO statements (filename, bank_name, card_last_4, statement_date, billing_month, raw_file_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "statement.json",
                "UOB",
                "4919",
                "2025-10-24",
                "2025-10",
                str(json_path),
            ),
        )
        conn.commit()

    classifications = refresh_statement_db.classify_files([json_path], db_path)

    assert len(classifications) == 1
    assert classifications[0].action == "refresh"
    assert classifications[0].matched_statement_id == 1


def test_classify_missing_statement_as_import(tmp_path):
    db_path = tmp_path / "backend.db"
    init_test_db(db_path)
    json_path = tmp_path / "statements" / "2025" / "11" / "uob" / "new_statement.json"
    write_json(
        json_path,
        {
            "filename": "new_statement.json",
            "bank_name": "UOB",
            "card_last_4": "2990",
            "statement_date": "2025-11-24",
            "transactions": [],
        },
    )

    classifications = refresh_statement_db.classify_files([json_path], db_path)

    assert len(classifications) == 1
    assert classifications[0].action == "import"
    assert classifications[0].matched_statement_id is None


def test_second_statement_same_month_different_date_is_import(tmp_path):
    db_path = tmp_path / "backend.db"
    init_test_db(db_path)
    json_path = tmp_path / "statements" / "2025" / "11" / "uob" / "statement_2.json"
    write_json(
        json_path,
        {
            "filename": "statement_2.json",
            "bank_name": "UOB",
            "card_last_4": "4919",
            "statement_date": "2025-11-24",
            "transactions": [],
        },
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO statements (filename, bank_name, card_last_4, statement_date, billing_month, raw_file_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "statement.json",
                "UOB",
                "4919",
                "2025-11-02",
                "2025-11",
                "old.json",
            ),
        )
        conn.commit()

    classifications = refresh_statement_db.classify_files([json_path], db_path)

    assert classifications[0].action == "import"


def test_account_last4_is_used_when_card_last4_missing(tmp_path):
    db_path = tmp_path / "backend.db"
    init_test_db(db_path)
    json_path = tmp_path / "statements" / "2026" / "03" / "uob" / "account.json"
    write_json(
        json_path,
        {
            "filename": "account.json",
            "bank_name": "UOB",
            "account_number_last_4": "1234",
            "statement_date": "2026-03-27",
            "transactions": [],
        },
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO statements (filename, bank_name, card_last_4, statement_date, billing_month, raw_file_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "account.json",
                "UOB",
                "1234",
                "2026-03-27",
                "2026-03",
                str(json_path),
            ),
        )
        conn.commit()

    classifications = refresh_statement_db.classify_files([json_path], db_path)

    assert classifications[0].action == "refresh"


def test_classify_existing_statement_as_refresh_by_raw_file_path_when_identity_changed(tmp_path):
    db_path = tmp_path / "backend.db"
    init_test_db(db_path)
    json_path = tmp_path / "statements" / "2025" / "10" / "uob" / "statement.json"
    write_json(
        json_path,
        {
            "filename": "statement.json",
            "bank_name": "UOB",
            "card_last_4": "4919",
            "statement_date": "2025-10-24",
            "transactions": [],
        },
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO statements (filename, bank_name, card_last_4, statement_date, billing_month, raw_file_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "statement.json",
                "UOB",
                "0000",
                "2025-10-01",
                "2025-10",
                str(json_path.resolve()),
            ),
        )
        conn.commit()

    classifications = refresh_statement_db.classify_files([json_path], db_path)

    assert classifications[0].action == "refresh"
    assert classifications[0].match_reason == "raw_file_path exact match"


def test_classify_ambiguous_filename_fallback_errors(tmp_path):
    db_path = tmp_path / "backend.db"
    init_test_db(db_path)
    json_path = tmp_path / "statements" / "2025" / "10" / "uob" / "statement.json"
    write_json(
        json_path,
        {
            "filename": "statement.json",
            "bank_name": "UOB",
            "card_last_4": "4919",
            "statement_date": "2025-10-24",
            "transactions": [],
        },
    )
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO statements (filename, bank_name, card_last_4, statement_date, billing_month, raw_file_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("statement.json", "UOB", "1111", "2025-10-01", "2025-10", "old_a.json"),
                ("statement.json", "UOB", "2222", "2025-10-02", "2025-10", "old_b.json"),
            ],
        )
        conn.commit()

    try:
        refresh_statement_db.classify_files([json_path], db_path)
    except ValueError as exc:
        assert "Ambiguous refresh match" in str(exc)
    else:
        raise AssertionError("Expected ambiguous filename fallback to raise ValueError")


def test_backend_db_path_comes_from_backend_env_not_root_env(tmp_path):
    repo_root = tmp_path / "repo"
    backend_dir = repo_root / "backend"
    backend_dir.mkdir(parents=True)
    (repo_root / ".env").write_text(
        "DATABASE_URL=sqlite:///./expense_tracker.db\n",
        encoding="utf-8",
    )
    (backend_dir / ".env").write_text(
        f"DATABASE_URL=sqlite:///{(backend_dir / 'expense_tracker.db').as_posix()}\n",
        encoding="utf-8",
    )

    backend_db_path = refresh_statement_db.get_backend_db_path(repo_root)
    root_db_path = refresh_statement_db.get_root_db_path(repo_root)

    assert backend_db_path == (backend_dir / "expense_tracker.db").resolve()
    assert root_db_path == (repo_root / "expense_tracker.db").resolve()


def test_cleanup_root_db_clears_target_transaction_references_only(tmp_path):
    db_path = tmp_path / "root.db"
    init_cleanup_test_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO statements (id, filename, bank_name, card_last_4, statement_date, billing_month, raw_file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "target.json", "UOB", "4919", "2025-10-24", "2025-10", "target.json"),
                (2, "other.json", "UOB", "8888", "2025-10-09", "2025-10", "other.json"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO transactions (id, statement_id, original_transaction_id, parent_transaction_id, resolved_by_transaction_id, resolved_method)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (11, 1, None, None, None, None),
                (12, 1, None, None, None, None),
                (99, 2, 11, 12, 11, "auto"),
                (1, 2, None, None, None, None),
            ],
        )
        conn.execute(
            "INSERT INTO bill_line_items (transaction_id) VALUES (?)",
            (11,),
        )
        conn.execute(
            "INSERT INTO ml_training_data (transaction_id) VALUES (?)",
            (12,),
        )
        conn.commit()

    identity = refresh_statement_db.StatementIdentity(
        json_path=str(tmp_path / "statements" / "2025" / "10" / "uob" / "target.json"),
        filename="target.json",
        bank_name="UOB",
        statement_date="2025-10-24",
        billing_month="2025-10",
        last4="4919",
    )

    summary = refresh_statement_db.cleanup_root_db(db_path, [identity])

    assert summary["deleted_statements"] == 1
    assert summary["deleted_transactions"] == 2
    assert summary["remaining_matches"] == 0

    with sqlite3.connect(db_path) as conn:
        remaining_statement_ids = [row[0] for row in conn.execute("SELECT id FROM statements").fetchall()]
        remaining_transaction_ids = [row[0] for row in conn.execute("SELECT id FROM transactions").fetchall()]
        row = conn.execute(
            """
            SELECT original_transaction_id, parent_transaction_id, resolved_by_transaction_id, resolved_method
            FROM transactions
            WHERE id = 99
            """
        ).fetchone()
        bill_line_item = conn.execute("SELECT transaction_id FROM bill_line_items").fetchone()[0]
        ml_training_count = conn.execute("SELECT COUNT(*) FROM ml_training_data").fetchone()[0]

    assert remaining_statement_ids == [2]
    assert sorted(remaining_transaction_ids) == [1, 99]
    assert row == (None, None, None, None)
    assert bill_line_item is None
    assert ml_training_count == 0
