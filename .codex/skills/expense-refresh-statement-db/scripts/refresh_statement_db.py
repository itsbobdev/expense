#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote


SQLITE_URL_PREFIX = "sqlite:///"


@dataclass(frozen=True)
class StatementIdentity:
    json_path: str
    filename: str
    bank_name: str
    statement_date: str
    billing_month: str
    last4: str


@dataclass(frozen=True)
class Classification:
    identity: StatementIdentity
    action: str
    matched_statement_id: int | None
    match_reason: str | None


@dataclass(frozen=True)
class ImportOutcome:
    json_path: str
    action: str
    status: str
    detail: str
    returncode: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely refresh the statement DB after corrected statement JSON extraction."
    )
    parser.add_argument(
        "json_paths",
        nargs="+",
        help="Explicit statement JSON file paths to refresh/import.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[4],
        help="Repository root. Defaults to the current repo.",
    )
    parser.add_argument(
        "--cleanup-root-db",
        action="store_true",
        help="Delete only the targeted statement identities from the repo-root SQLite DB after the backend update.",
    )
    return parser.parse_args()


def read_env_value(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() != key:
            continue
        value = value.strip().strip('"').strip("'")
        return value
    return None


def sqlite_path_from_url(database_url: str, relative_to: Path) -> Path:
    if not database_url.startswith(SQLITE_URL_PREFIX):
        raise ValueError(f"Only sqlite DATABASE_URL values are supported, got: {database_url}")
    raw_path = unquote(database_url[len(SQLITE_URL_PREFIX):])
    if re.match(r"^[A-Za-z]:[\\/]", raw_path):
        return Path(raw_path).resolve()
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    return (relative_to / path).resolve()


def get_backend_db_path(repo_root: Path) -> Path:
    env_path = repo_root / "backend" / ".env"
    database_url = read_env_value(env_path, "DATABASE_URL")
    if not database_url:
        raise ValueError(f"DATABASE_URL not found in {env_path}")
    return sqlite_path_from_url(database_url, repo_root / "backend")


def get_root_db_path(repo_root: Path) -> Path | None:
    env_path = repo_root / ".env"
    database_url = read_env_value(env_path, "DATABASE_URL")
    if not database_url:
        return None
    return sqlite_path_from_url(database_url, repo_root)


def derive_billing_month(json_path: Path) -> str:
    parts = list(json_path.resolve().parts)
    for index, part in enumerate(parts):
        if len(part) == 4 and part.isdigit() and index + 1 < len(parts):
            month_part = parts[index + 1]
            if len(month_part) == 2 and month_part.isdigit():
                return f"{part}-{month_part}"
    raise ValueError(f"Cannot determine billing month from path: {json_path}")


def load_statement_identity(json_path: Path) -> StatementIdentity:
    resolved = json_path.resolve()
    if resolved.suffix.lower() != ".json":
        raise ValueError(f"Expected a JSON file path, got: {json_path}")
    data = json.loads(resolved.read_text(encoding="utf-8"))
    bank_name = data.get("bank_name")
    statement_date = data.get("statement_date")
    last4 = data.get("card_last_4") or data.get("account_number_last_4")
    if not bank_name or not statement_date or not last4:
        raise ValueError(
            f"Missing bank_name, statement_date, or last4 identity fields in {json_path}"
        )
    return StatementIdentity(
        json_path=str(resolved),
        filename=data.get("filename") or resolved.name,
        bank_name=str(bank_name),
        statement_date=str(statement_date),
        billing_month=derive_billing_month(resolved),
        last4=str(last4),
    )


def normalize_path_value(path_value: str | Path | None) -> str:
    if not path_value:
        return ""
    return str(path_value).replace("\\", "/").strip().casefold()


def statement_path_suffix(path_value: str | Path | None) -> str:
    normalized = normalize_path_value(path_value)
    if not normalized:
        return ""
    marker = "/statements/"
    if marker in normalized:
        return "statements/" + normalized.split(marker, 1)[1]
    return Path(str(path_value)).name.casefold()


def sibling_jsons_share_source_filename(identity: StatementIdentity) -> bool:
    json_path = Path(identity.json_path)
    try:
        sibling_paths = sorted(json_path.parent.glob("*.json"))
    except FileNotFoundError:
        return False

    matches = 0
    for sibling in sibling_paths:
        try:
            data = json.loads(sibling.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("filename") or "") != identity.filename:
            continue
        if derive_billing_month(sibling.resolve()) != identity.billing_month:
            continue
        matches += 1
        if matches > 1:
            return True
    return False


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def resolve_refresh_match(
    conn: sqlite3.Connection,
    identity: StatementIdentity,
) -> tuple[int | None, str | None]:
    row = conn.execute(
        """
        SELECT id
        FROM statements
        WHERE bank_name = ?
          AND card_last_4 = ?
          AND statement_date = ?
          AND billing_month = ?
        LIMIT 1
        """,
        (
            identity.bank_name,
            identity.last4,
            identity.statement_date,
            identity.billing_month,
        ),
    ).fetchone()
    if row:
        return int(row["id"]), "bank/card/date/month match"

    candidates = conn.execute(
        """
        SELECT id, filename, raw_file_path
        FROM statements
        WHERE billing_month = ?
        """,
        (identity.billing_month,),
    ).fetchall()
    input_abs = normalize_path_value(identity.json_path)
    input_suffix = statement_path_suffix(identity.json_path)
    normalized_filename = identity.filename.casefold()

    exact_path_matches = [
        int(candidate["id"])
        for candidate in candidates
        if normalize_path_value(candidate["raw_file_path"]) == input_abs
    ]
    if len(exact_path_matches) == 1:
        return exact_path_matches[0], "raw_file_path exact match"
    if len(exact_path_matches) > 1:
        raise ValueError(
            f"Ambiguous refresh match for {identity.json_path}: multiple existing statements match the same raw file path"
        )

    suffix_matches = [
        int(candidate["id"])
        for candidate in candidates
        if normalize_path_value(candidate["raw_file_path"]).endswith(input_suffix)
    ]
    if len(suffix_matches) == 1:
        return suffix_matches[0], "statement path suffix match"
    if len(suffix_matches) > 1:
        raise ValueError(
            f"Ambiguous refresh match for {identity.json_path}: multiple existing statements match the same statement path suffix"
        )

    filename_matches = [
        int(candidate["id"])
        for candidate in candidates
        if (candidate["filename"] or "").casefold() == normalized_filename
    ]
    if filename_matches and sibling_jsons_share_source_filename(identity):
        return None, None
    if len(filename_matches) == 1:
        return filename_matches[0], "filename+billing_month fallback"
    if len(filename_matches) > 1:
        raise ValueError(
            f"Ambiguous refresh match for {identity.json_path}: multiple existing statements share filename {identity.filename!r} in billing month {identity.billing_month}"
        )
    return None, None


def classify_files(json_paths: Iterable[Path], backend_db_path: Path) -> list[Classification]:
    identities = [load_statement_identity(path) for path in json_paths]
    with sqlite3.connect(backend_db_path) as conn:
        conn.row_factory = sqlite3.Row
        results: list[Classification] = []
        for identity in identities:
            matched_statement_id, match_reason = resolve_refresh_match(conn, identity)
            if matched_statement_id is not None:
                results.append(
                    Classification(
                        identity=identity,
                        action="refresh",
                        matched_statement_id=matched_statement_id,
                        match_reason=match_reason,
                    )
                )
            else:
                results.append(
                    Classification(
                        identity=identity,
                        action="import",
                        matched_statement_id=None,
                        match_reason=None,
                    )
                )
        return results


def parse_importer_status(stdout: str) -> tuple[str, str]:
    status_line = None
    for line in stdout.splitlines():
        line = line.strip()
        if "[OK]" in line or "[SKIP]" in line or "[ERROR]" in line:
            status_line = line
            break
    if not status_line:
        return "ERROR", "importer output did not contain a per-file status line"
    match = re.search(r"\[(OK|SKIP|ERROR)\]\s*(.+)$", status_line)
    if not match:
        return "ERROR", status_line
    return match.group(1), match.group(2).strip()


def run_import(backend_dir: Path, json_path: Path, refresh_existing: bool) -> ImportOutcome:
    command = [sys.executable, "import_statements.py"]
    if refresh_existing:
        command.append("--refresh")
    command.append(str(json_path.resolve()))
    result = subprocess.run(
        command,
        cwd=backend_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    status, detail = parse_importer_status(result.stdout)
    if status == "ERROR" and detail == "importer output did not contain a per-file status line":
        stderr = result.stderr.strip()
        if stderr:
            detail = stderr
    if result.returncode != 0 and status != "ERROR":
        stderr = result.stderr.strip() or "importer exited with non-zero status"
        status = "ERROR"
        detail = stderr
    return ImportOutcome(
        json_path=str(json_path.resolve()),
        action="refresh" if refresh_existing else "import",
        status=status,
        detail=detail,
        returncode=result.returncode,
    )


def verify_no_duplicates(backend_db_path: Path, identities: Iterable[StatementIdentity]) -> list[dict]:
    checks: list[dict] = []
    with sqlite3.connect(backend_db_path) as conn:
        for identity in identities:
            count = conn.execute(
                """
                SELECT COUNT(*)
                FROM statements
                WHERE bank_name = ?
                  AND card_last_4 = ?
                  AND statement_date = ?
                  AND billing_month = ?
                """,
                (
                    identity.bank_name,
                    identity.last4,
                    identity.statement_date,
                    identity.billing_month,
                ),
            ).fetchone()[0]
            checks.append(
                {
                    "json_path": identity.json_path,
                    "bank_name": identity.bank_name,
                    "last4": identity.last4,
                    "statement_date": identity.statement_date,
                    "billing_month": identity.billing_month,
                    "match_count": count,
                }
            )
    return checks


def _get_transaction_ids_for_statements(conn: sqlite3.Connection, statement_ids: list[int]) -> list[int]:
    if not statement_ids:
        return []
    placeholders = ",".join("?" for _ in statement_ids)
    if not table_exists(conn, "transactions"):
        return []
    rows = conn.execute(
        f"SELECT id FROM transactions WHERE statement_id IN ({placeholders})",
        statement_ids,
    ).fetchall()
    return [int(row[0]) for row in rows]


def _safe_delete_targeted_statements(conn: sqlite3.Connection, statement_ids: list[int]) -> tuple[int, int]:
    if not statement_ids:
        return 0, 0

    placeholders = ",".join("?" for _ in statement_ids)
    transaction_ids = _get_transaction_ids_for_statements(conn, statement_ids)
    txn_placeholders = ",".join("?" for _ in transaction_ids) if transaction_ids else ""

    # Clear dependent references first so cleanup mirrors the importer refresh semantics.
    if transaction_ids and table_exists(conn, "bill_line_items"):
        conn.execute(
            f"UPDATE bill_line_items SET transaction_id = NULL WHERE transaction_id IN ({txn_placeholders})",
            transaction_ids,
        )
    if transaction_ids and table_exists(conn, "ml_training_data"):
        conn.execute(
            f"DELETE FROM ml_training_data WHERE transaction_id IN ({txn_placeholders})",
            transaction_ids,
        )
    if transaction_ids and table_exists(conn, "transactions"):
        conn.execute(
            f"UPDATE transactions SET original_transaction_id = NULL WHERE original_transaction_id IN ({txn_placeholders})",
            transaction_ids,
        )
        conn.execute(
            f"UPDATE transactions SET parent_transaction_id = NULL WHERE parent_transaction_id IN ({txn_placeholders})",
            transaction_ids,
        )
        conn.execute(
            f"""
            UPDATE transactions
            SET resolved_by_transaction_id = NULL,
                resolved_method = NULL
            WHERE resolved_by_transaction_id IN ({txn_placeholders})
            """,
            transaction_ids,
        )

    deleted_transactions = 0
    if table_exists(conn, "transactions"):
        deleted_transactions = conn.execute(
            f"DELETE FROM transactions WHERE statement_id IN ({placeholders})",
            statement_ids,
        ).rowcount
    deleted_statements = conn.execute(
        f"DELETE FROM statements WHERE id IN ({placeholders})",
        statement_ids,
    ).rowcount
    return deleted_statements, deleted_transactions


def cleanup_root_db(root_db_path: Path, identities: Iterable[StatementIdentity]) -> dict:
    if not root_db_path.exists():
        return {
            "db_path": str(root_db_path),
            "deleted_statements": 0,
            "deleted_transactions": 0,
            "remaining_matches": 0,
        }

    deleted_statements = 0
    deleted_transactions = 0
    remaining_matches = 0
    with sqlite3.connect(root_db_path) as conn:
        if not table_exists(conn, "statements"):
            return {
                "db_path": str(root_db_path),
                "deleted_statements": 0,
                "deleted_transactions": 0,
                "remaining_matches": 0,
            }
        for identity in identities:
            rows = conn.execute(
                """
                SELECT id
                FROM statements
                WHERE bank_name = ?
                  AND card_last_4 = ?
                  AND statement_date = ?
                  AND billing_month = ?
                """,
                (
                    identity.bank_name,
                    identity.last4,
                    identity.statement_date,
                    identity.billing_month,
                ),
            ).fetchall()
            statement_ids = [row[0] for row in rows]
            if statement_ids:
                removed_statements, removed_transactions = _safe_delete_targeted_statements(
                    conn, statement_ids
                )
                deleted_statements += removed_statements
                deleted_transactions += removed_transactions
        conn.commit()
        for identity in identities:
            remaining_matches += conn.execute(
                """
                SELECT COUNT(*)
                FROM statements
                WHERE bank_name = ?
                  AND card_last_4 = ?
                  AND statement_date = ?
                  AND billing_month = ?
                """,
                (
                    identity.bank_name,
                    identity.last4,
                    identity.statement_date,
                    identity.billing_month,
                ),
            ).fetchone()[0]
    return {
        "db_path": str(root_db_path),
        "deleted_statements": deleted_statements,
        "deleted_transactions": deleted_transactions,
        "remaining_matches": remaining_matches,
    }


def unique_paths(paths: Iterable[str]) -> list[Path]:
    ordered: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path).resolve()
        if path in seen:
            continue
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        seen.add(path)
        ordered.append(path)
    return ordered


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    backend_dir = repo_root / "backend"
    import_script = backend_dir / "import_statements.py"
    if not import_script.exists():
        raise FileNotFoundError(f"Expected importer at {import_script}")
    backend_db_path = get_backend_db_path(repo_root)
    root_db_path = get_root_db_path(repo_root)
    json_paths = unique_paths(args.json_paths)
    classifications = classify_files(json_paths, backend_db_path)
    refresh_items = [item for item in classifications if item.action == "refresh"]
    import_items = [item for item in classifications if item.action == "import"]

    print(f"Repo root: {repo_root}")
    print(f"Backend dir: {backend_dir}")
    print(f"Backend DB target: {backend_db_path}")
    print(f"Refresh files: {len(refresh_items)}")
    for item in refresh_items:
        print(f"  - {item.identity.json_path}")
    print(f"Normal import files: {len(import_items)}")
    for item in import_items:
        print(f"  - {item.identity.json_path}")

    outcomes: list[ImportOutcome] = []
    for item in refresh_items:
        outcomes.append(run_import(backend_dir, Path(item.identity.json_path), refresh_existing=True))
    for item in import_items:
        outcomes.append(run_import(backend_dir, Path(item.identity.json_path), refresh_existing=False))

    duplicate_checks = verify_no_duplicates(
        backend_db_path,
        [item.identity for item in classifications],
    )
    cleanup_summary = None
    if args.cleanup_root_db and root_db_path and root_db_path != backend_db_path:
        cleanup_summary = cleanup_root_db(root_db_path, [item.identity for item in classifications])

    summary = {
        "backend_db_path": str(backend_db_path),
        "refresh_files": [
            {
                "json_path": item.identity.json_path,
                "matched_statement_id": item.matched_statement_id,
                "match_reason": item.match_reason,
            }
            for item in refresh_items
        ],
        "import_files": [item.identity.json_path for item in import_items],
        "outcomes": [asdict(outcome) for outcome in outcomes],
        "duplicate_checks": duplicate_checks,
        "root_cleanup": cleanup_summary,
    }
    print("SUMMARY_JSON:")
    print(json.dumps(summary, indent=2))

    if any(outcome.status == "ERROR" for outcome in outcomes):
        return 1
    if any(check["match_count"] > 1 for check in duplicate_checks):
        return 1
    if cleanup_summary and cleanup_summary["remaining_matches"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
