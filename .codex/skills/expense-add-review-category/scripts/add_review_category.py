from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add a self-review blacklist category to the expense repo and backfill the local database."
    )
    parser.add_argument("--category", required=True, help="Category name, e.g. atome")
    parser.add_argument(
        "--keyword",
        action="append",
        dest="keywords",
        required=True,
        help="Keyword used for matching. Repeat for multiple keywords.",
    )
    parser.add_argument(
        "--rule-text",
        required=True,
        help="Rule text to insert into the extraction guides.",
    )
    parser.add_argument(
        "--example-merchant",
        required=True,
        help="Example merchant string for the docs.",
    )
    parser.add_argument(
        "--example-categories",
        default="",
        help="Comma-separated example categories, defaults to just the category being added.",
    )
    parser.add_argument(
        "--db-path",
        default=str(ROOT / "backend" / "expense_tracker.db"),
        help="Path to the SQLite database to backfill.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned changes without writing files or database rows.",
    )
    return parser.parse_args()


def normalize_keywords(keywords: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for keyword in keywords:
        if not keyword.strip():
            continue
        value = keyword
        lower = value.lower()
        if lower in seen:
            continue
        seen.add(lower)
        normalized.append(value)
    return normalized


def insert_category_into_set(text: str, category: str) -> str:
    needle = "REVIEW_TRIGGER_CATEGORIES: Set[str] = {"
    if f'    "{category}",' in text:
        return text
    index = text.index(needle) + len(needle)
    closing = text.index("}", index)
    block = text[index:closing]
    if block and not block.endswith("\n"):
        block += "\n"
    block += f'    "{category}",\n'
    return text[:index] + block + text[closing:]


def insert_seed_category(text: str, category: str, keywords: list[str]) -> str:
    if f'"name": "{category}"' in text:
        return text

    marker = "\n    ]\n"
    category_block = [
        "        {",
        f'            "name": "{category}",',
        '            "keywords": [',
    ]
    for keyword in keywords:
        category_block.append(f'                "{keyword}",')
    category_block.extend(
        [
            "            ],",
            '            "is_active": True,',
            "        },",
        ]
    )
    insert = "\n" + "\n".join(category_block)
    return text.replace(marker, f"{insert}{marker}", 1)


def insert_doc_rows(
    text: str,
    category: str,
    rule_text: str,
    example_merchant: str,
    example_categories: list[str],
) -> str:
    rule_row = f"| `{category}` | {rule_text} |"
    if rule_row not in text:
        text = text.replace(
            "| `paypal` | `merchant_name` starts with `PAYPAL *` or `PAYPAL*` |\n",
            f"{rule_row}\n| `paypal` | `merchant_name` starts with `PAYPAL *` or `PAYPAL*` |\n",
            1,
        )

    categories_json = json.dumps(example_categories)
    example_row = f'| `{example_merchant}` | `null` | `{categories_json}` |'
    if example_row not in text:
        text = text.replace(
            '| `PAYPAL *SMARTVISION SM` | `null` | `["paypal"]` |\n',
            f"{example_row}\n| `PAYPAL *SMARTVISION SM` | `null` | `[\"paypal\"]` |\n",
            1,
        )
    return text


def write_text(path: Path, text: str, dry_run: bool) -> None:
    if dry_run:
        return
    path.write_text(text, encoding="utf-8")


def sql_patterns_from_keywords(keywords: Iterable[str]) -> list[str]:
    patterns: list[str] = []
    for keyword in keywords:
        keyword = keyword.lower()
        if keyword.endswith("*"):
            patterns.append(keyword[:-1] + "%")
        else:
            patterns.append("%" + keyword + "%")
    return patterns


def backfill_database(db_path: Path, category: str, keywords: list[str], dry_run: bool) -> dict[str, int]:
    if not db_path.exists():
        return {"db_exists": 0, "category_created": 0, "rows_backfilled": 0}

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, keywords FROM blacklist_categories WHERE name = ?", (category,))
        row = cur.fetchone()
        created = 0
        if row:
            category_id = row[0]
            existing_keywords = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or [])
            merged = existing_keywords[:]
            existing_lower = {str(k).lower() for k in existing_keywords}
            for keyword in keywords:
                if keyword.lower() not in existing_lower:
                    merged.append(keyword)
            if not dry_run:
                cur.execute(
                    "UPDATE blacklist_categories SET keywords = ?, is_active = 1 WHERE id = ?",
                    (json.dumps(merged), category_id),
                )
        else:
            created = 1
            if not dry_run:
                cur.execute(
                    "INSERT INTO blacklist_categories (name, keywords, is_active) VALUES (?, ?, 1)",
                    (category, json.dumps(keywords)),
                )
                category_id = cur.lastrowid
            else:
                category_id = -1

        patterns = sql_patterns_from_keywords(keywords)
        base_query = """
            SELECT id, categories
            FROM transactions
            WHERE assigned_to_person_id IN (
                SELECT id FROM persons WHERE relationship_type = 'self'
            )
              AND ifnull(is_refund, 0) = 0
              AND ifnull(is_reward, 0) = 0
              AND ifnull(assignment_method, '') != 'manual'
              AND (
        """
        predicates = " OR ".join(["lower(merchant_name) LIKE ?"] * len(patterns))
        tail_query = """
              )
        """
        rows = list(cur.execute(base_query + predicates + tail_query, patterns))

        updated = 0
        for txn_id, categories_raw in rows:
            if isinstance(categories_raw, str) and categories_raw:
                categories = json.loads(categories_raw)
            else:
                categories = categories_raw or []
            if category not in categories:
                categories.append(category)
            updated += 1
            if not dry_run:
                cur.execute(
                    """
                    UPDATE transactions
                    SET categories = ?,
                        assignment_confidence = 0.0,
                        assignment_method = 'category_review',
                        needs_review = 1,
                        reviewed_at = NULL,
                        blacklist_category_id = ?
                    WHERE id = ?
                    """,
                    (json.dumps(categories), category_id, txn_id),
                )

        if not dry_run:
            conn.commit()
        return {"db_exists": 1, "category_created": created, "rows_backfilled": updated}
    finally:
        conn.close()


def main() -> None:
    args = parse_args()
    category = args.category.strip().lower()
    keywords = normalize_keywords(args.keywords)
    example_categories = [
        item.strip() for item in (args.example_categories.split(",") if args.example_categories else [category]) if item.strip()
    ]
    if not example_categories:
        example_categories = [category]

    files = {
        "categorizer": ROOT / "backend" / "app" / "services" / "categorizer.py",
        "yaml_loader": ROOT / "backend" / "app" / "utils" / "yaml_loader.py",
        "claude_guide": ROOT / ".claude" / "commands" / "guide_extract_statement_command.md",
        "codex_categories": ROOT / ".codex" / "skills" / "expense-extract-statements" / "references" / "categories.md",
    }

    categorizer_text = files["categorizer"].read_text(encoding="utf-8")
    yaml_loader_text = files["yaml_loader"].read_text(encoding="utf-8")
    claude_guide_text = files["claude_guide"].read_text(encoding="utf-8")
    codex_categories_text = files["codex_categories"].read_text(encoding="utf-8")

    categorizer_text = insert_category_into_set(categorizer_text, category)
    yaml_loader_text = insert_seed_category(yaml_loader_text, category, keywords)
    claude_guide_text = insert_doc_rows(
        claude_guide_text, category, args.rule_text, args.example_merchant, example_categories
    )
    codex_categories_text = insert_doc_rows(
        codex_categories_text, category, args.rule_text, args.example_merchant, example_categories
    )

    write_text(files["categorizer"], categorizer_text, args.dry_run)
    write_text(files["yaml_loader"], yaml_loader_text, args.dry_run)
    write_text(files["claude_guide"], claude_guide_text, args.dry_run)
    write_text(files["codex_categories"], codex_categories_text, args.dry_run)

    db_result = backfill_database(Path(args.db_path), category, keywords, args.dry_run)

    result = {
        "category": category,
        "keywords": keywords,
        "files_updated": 4,
        "db_result": db_result,
        "dry_run": args.dry_run,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
