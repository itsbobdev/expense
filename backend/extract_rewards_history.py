"""
Backfill statement rewards into statements/rewards_history.json.

This script is intended for retrospective extraction after transaction JSON files
already exist. It combines:

1. PDF summary extraction where the repo has reliable statement-level reward text
   today:
   - Citi points / miles / cashback summaries
   - Maybank TREATS points summaries from World Mastercard PDFs
2. Existing statement JSON transaction lines for cashback rewards:
   - Maybank cashback transactions
   - UOB cashback transactions

Current limitations:
- HSBC statements in this repo are image-only and are reported as skipped.

Usage:
    cd backend && python extract_rewards_history.py
    cd backend && python extract_rewards_history.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pdfplumber

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings


CITI_POINTS_MARKER = "YOURCITITHANKYOUPOINTSBALANCESUMMARY"
CITI_MILES_MARKER = "YOURCITIMILESSUMMARY"
CITI_CASHBACK_MARKER = "YOURCASHBACKSUMMARY"
MAYBANK_TREATS_MARKER = "TREATS POINTS REWARDS SUMMARY AS AT"
UOB_REWARDS_MARKER = "Rewards Summary"

MAYBANK_CASHBACK_PATTERNS = (
    re.compile(r"^\d+%\s*CASHBACK$", re.IGNORECASE),
    re.compile(r"^OTHER CASHBACK$", re.IGNORECASE),
)
UOB_CASHBACK_PATTERNS = (
    re.compile(r"^UOB EVOL Card Cashback", re.IGNORECASE),
    re.compile(r"^UOB Absolute Cashback", re.IGNORECASE),
)

YEAR_PART = re.compile(r"^\d{4}$")
MONTH_PART = re.compile(r"^\d{2}$")
CARD_NUMBER_GENERIC = re.compile(r"(?:\d{4}[- ]?){3}\d{3,5}")
UOB_SUMMARY_LINE = re.compile(
    r"UNI\$\s*-\s*([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+-?|-[\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+(\d{2}/\d{2}/\d{4})"
)


@dataclass
class RewardEntry:
    billing_month: str
    bank_name: str
    card_last_4: str
    reward_type: str
    earned_this_period: float
    balance: float | None
    expiry_date: str | None
    description: str

    def to_dict(self) -> dict:
        return {
            "billing_month": self.billing_month,
            "bank_name": self.bank_name,
            "card_last_4": self.card_last_4,
            "reward_type": self.reward_type,
            "earned_this_period": self.earned_this_period,
            "balance": self.balance,
            "expiry_date": self.expiry_date,
            "description": self.description,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill rewards_history.json from PDFs and existing statement JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing rewards_history.json.")
    return parser.parse_args()


def resolve_statements_dir() -> Path:
    statements_dir = settings.statements_dir
    if statements_dir.is_absolute():
        return statements_dir
    return (Path(__file__).resolve().parent / statements_dir).resolve()


def uob_rewards_card_last4() -> str:
    # Per user instruction, do not split combined UOB rewards summaries by card.
    # Attribute them to Lady's Solitaire only.
    return "5750"


def billing_month_from_path(path: Path) -> str | None:
    parts = path.parts
    for i in range(len(parts) - 2):
        if YEAR_PART.match(parts[i]) and MONTH_PART.match(parts[i + 1]):
            return f"{parts[i]}-{parts[i + 1]}"
    return None


def iter_statement_pdfs(statements_dir: Path) -> Iterable[Path]:
    for path in statements_dir.rglob("*.pdf"):
        lowered = {part.lower() for part in path.parts}
        if ".claude" in lowered or "test" in lowered:
            continue
        yield path


def iter_statement_json_files(statements_dir: Path) -> Iterable[Path]:
    for path in statements_dir.rglob("*.json"):
        lowered = {part.lower() for part in path.parts}
        if ".claude" in lowered or "test" in lowered:
            continue
        if path.name == "rewards_history.json":
            continue
        yield path


def get_pdf_text_pages(path: Path) -> list[str]:
    with pdfplumber.open(path) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def parse_numeric_tokens(line: str) -> list[float]:
    values = []
    for token in re.findall(r"-?\d[\d,]*(?:\.\d+)?", line):
        values.append(float(token.replace(",", "")))
    return values


def card_last4_from_page_text(text: str) -> str | None:
    matches = CARD_NUMBER_GENERIC.findall(text)
    if matches:
        digits = re.sub(r"[^0-9]", "", matches[-1])
        return digits[-4:]
    return None


def find_summary_numbers(lines: list[str], marker_predicate) -> list[float] | None:
    start = None
    for idx, line in enumerate(lines):
        if marker_predicate(line):
            start = idx
            break
    if start is None:
        return None

    for line in lines[start + 1 : start + 12]:
        numbers = parse_numeric_tokens(line)
        if len(numbers) >= 6:
            return numbers
    return None


def find_summary_numbers_after_index(lines: list[str], start: int) -> list[float] | None:
    for line in lines[start + 1 : start + 12]:
        numbers = parse_numeric_tokens(line)
        if len(numbers) >= 6:
            return numbers
    return None


def extract_citi_rewards(pdf_path: Path) -> tuple[list[RewardEntry], list[str]]:
    entries: list[RewardEntry] = []
    warnings: list[str] = []
    billing_month = billing_month_from_path(pdf_path)
    if not billing_month:
        warnings.append(f"{pdf_path}: could not infer billing month")
        return entries, warnings

    for page_text in get_pdf_text_pages(pdf_path):
        if not page_text:
            continue

        lines = page_text.splitlines()
        compact_lines = [line.replace(" ", "") for line in lines]
        compact_text = "\n".join(compact_lines)
        card_last_4 = card_last4_from_page_text(page_text)

        if CITI_POINTS_MARKER in compact_text:
            marker_index = next((i for i, line in enumerate(compact_lines) if CITI_POINTS_MARKER in line), None)
            numbers = find_summary_numbers_after_index(lines, marker_index) if marker_index is not None else None
            if numbers and card_last_4 and len(numbers) >= 7:
                entries.append(
                    RewardEntry(
                        billing_month=billing_month,
                        bank_name="Citibank",
                        card_last_4=card_last_4,
                        reward_type="points",
                        earned_this_period=numbers[1] + numbers[2],
                        balance=numbers[-1],
                        expiry_date=None,
                        description="Citi ThankYou Points",
                    )
                )
            continue

        if CITI_MILES_MARKER in compact_text:
            marker_index = next((i for i, line in enumerate(compact_lines) if CITI_MILES_MARKER in line), None)
            numbers = find_summary_numbers_after_index(lines, marker_index) if marker_index is not None else None
            if numbers and card_last_4 and len(numbers) >= 6:
                entries.append(
                    RewardEntry(
                        billing_month=billing_month,
                        bank_name="Citibank",
                        card_last_4=card_last_4,
                        reward_type="miles",
                        earned_this_period=numbers[1] + numbers[2],
                        balance=numbers[-1],
                        expiry_date=None,
                        description="Citi Miles",
                    )
                )
            continue

        if CITI_CASHBACK_MARKER in compact_text:
            marker_index = next((i for i, line in enumerate(compact_lines) if CITI_CASHBACK_MARKER in line), None)
            numbers = find_summary_numbers_after_index(lines, marker_index) if marker_index is not None else None
            if numbers and card_last_4 and len(numbers) >= 7:
                entries.append(
                    RewardEntry(
                        billing_month=billing_month,
                        bank_name="Citibank",
                        card_last_4=card_last_4,
                        reward_type="cashback",
                        earned_this_period=numbers[1] + numbers[2],
                        balance=numbers[-1],
                        expiry_date=None,
                        description="Citi Cashback",
                    )
                )

    return entries, warnings


def extract_maybank_points(pdf_path: Path) -> tuple[list[RewardEntry], list[str]]:
    entries: list[RewardEntry] = []
    warnings: list[str] = []
    billing_month = billing_month_from_path(pdf_path)
    if not billing_month:
        warnings.append(f"{pdf_path}: could not infer billing month")
        return entries, warnings

    # Current repo samples show the TREATS points summary duplicated across
    # multiple Maybank product PDFs for the same principal. To avoid double
    # counting, backfill statement-level points only from World Mastercard PDFs.
    if "world_mastercard" not in pdf_path.name.lower():
        return entries, warnings

    for page_text in get_pdf_text_pages(pdf_path):
        if MAYBANK_TREATS_MARKER not in page_text:
            continue

        lines = page_text.splitlines()
        numbers = find_summary_numbers(lines, lambda line: MAYBANK_TREATS_MARKER in line)
        card_last_4 = card_last4_from_page_text(page_text)
        if numbers and card_last_4 and len(numbers) >= 5:
            entries.append(
                RewardEntry(
                    billing_month=billing_month,
                    bank_name="Maybank",
                    card_last_4=card_last_4,
                    reward_type="points",
                    earned_this_period=numbers[1],
                    balance=numbers[4],
                    expiry_date=None,
                    description="TREATS Points Summary",
                )
            )

    return entries, warnings


def parse_uob_summary_line(line: str) -> tuple[float, float, str] | None:
    match = UOB_SUMMARY_LINE.search(line)
    if not match:
        return None

    earned = float(match.group(2).replace(",", ""))
    current_balance = float(match.group(5).replace(",", ""))
    expiry_date = match.group(7)
    day, month, year = expiry_date.split("/")
    return earned, current_balance, f"{year}-{month}-{day}"


def extract_uob_uni_dollars(pdf_path: Path) -> tuple[list[RewardEntry], list[str]]:
    entries: list[RewardEntry] = []
    warnings: list[str] = []
    billing_month = billing_month_from_path(pdf_path)
    if not billing_month:
        warnings.append(f"{pdf_path}: could not infer billing month")
        return entries, warnings

    if "creditcard_combined" not in pdf_path.name.lower():
        return entries, warnings

    for page_text in get_pdf_text_pages(pdf_path):
        if UOB_REWARDS_MARKER not in page_text:
            continue

        lines = page_text.splitlines()
        summary_line = next((line for line in lines if line.startswith("UNI$ - ")), None)
        if not summary_line:
            warnings.append(f"{pdf_path}: found UOB rewards page but could not parse UNI$ summary line")
            continue

        parsed = parse_uob_summary_line(summary_line)
        if not parsed:
            warnings.append(f"{pdf_path}: found UOB rewards page but could not parse numeric fields")
            continue

        earned, balance, expiry_date = parsed
        detail_lines = []
        capture = False
        for line in lines:
            if line == UOB_REWARDS_MARKER:
                capture = True
                continue
            if line.startswith("Card Number"):
                break
            if capture and line.strip():
                detail_lines.append(line.strip())

        description = " | ".join(detail_lines) if detail_lines else "Rewards Summary"
        entries.append(
            RewardEntry(
                billing_month=billing_month,
                bank_name="UOB",
                card_last_4=uob_rewards_card_last4(),
                reward_type="uni_dollars",
                earned_this_period=earned,
                balance=balance,
                expiry_date=expiry_date,
                description=description,
            )
        )
        break

    return entries, warnings


def match_any(patterns: tuple[re.Pattern, ...], merchant_name: str) -> bool:
    return any(pattern.match(merchant_name or "") for pattern in patterns)


def description_for_cashback(names: list[str]) -> str:
    ordered = []
    for preferred in ("8% CASHBACK", "OTHER CASHBACK", "UOB EVOL Card Cashback", "UOB Absolute Cashback"):
        if preferred in names:
            ordered.append(preferred)
    for name in sorted(names):
        if name not in ordered:
            ordered.append(name)
    return " + ".join(ordered)


def extract_cashback_from_json(json_path: Path) -> tuple[list[RewardEntry], list[str]]:
    entries: list[RewardEntry] = []
    warnings: list[str] = []
    billing_month = billing_month_from_path(json_path)
    if not billing_month:
        warnings.append(f"{json_path}: could not infer billing month")
        return entries, warnings

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"{json_path}: failed to read JSON ({exc})")
        return entries, warnings

    bank_name = payload.get("bank_name")
    card_last_4 = payload.get("card_last_4")
    transactions = payload.get("transactions") or []
    if not bank_name or not card_last_4 or not isinstance(transactions, list):
        return entries, warnings

    if bank_name == "Maybank":
        patterns = MAYBANK_CASHBACK_PATTERNS
    elif bank_name == "UOB":
        patterns = UOB_CASHBACK_PATTERNS
    else:
        return entries, warnings

    matched = []
    total = 0.0
    for txn in transactions:
        merchant_name = txn.get("merchant_name") or ""
        if not match_any(patterns, merchant_name):
            continue
        amount = txn.get("amount")
        if amount is None:
            continue
        matched.append(merchant_name)
        total += abs(float(amount))

    if total > 0:
        entries.append(
            RewardEntry(
                billing_month=billing_month,
                bank_name=bank_name,
                card_last_4=card_last_4,
                reward_type="cashback",
                earned_this_period=round(total, 2),
                balance=None,
                expiry_date=None,
                description=description_for_cashback(sorted(set(matched))),
            )
        )

    return entries, warnings


def collect_entries(statements_dir: Path) -> tuple[list[RewardEntry], list[str]]:
    entries: list[RewardEntry] = []
    warnings: list[str] = []

    for pdf_path in iter_statement_pdfs(statements_dir):
        bank = pdf_path.parts[-2].lower() if len(pdf_path.parts) >= 2 else ""
        if bank == "citi":
            found, found_warnings = extract_citi_rewards(pdf_path)
            entries.extend(found)
            warnings.extend(found_warnings)
        elif bank == "maybank":
            found, found_warnings = extract_maybank_points(pdf_path)
            entries.extend(found)
            warnings.extend(found_warnings)
        elif bank == "hsbc":
            warnings.append(f"{pdf_path}: skipped HSBC rewards extraction (image-based PDF, no OCR path configured)")
        elif bank == "uob":
            found, found_warnings = extract_uob_uni_dollars(pdf_path)
            entries.extend(found)
            warnings.extend(found_warnings)

    for json_path in iter_statement_json_files(statements_dir):
        found, found_warnings = extract_cashback_from_json(json_path)
        entries.extend(found)
        warnings.extend(found_warnings)

    deduped: dict[tuple[str, str, str], RewardEntry] = {}
    for entry in entries:
        key = (entry.billing_month, entry.card_last_4, entry.reward_type)
        deduped[key] = entry

    return sorted(deduped.values(), key=lambda e: (e.billing_month, e.bank_name, e.card_last_4, e.reward_type)), warnings


def load_existing_rewards(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_rewards(path: Path, entries: list[RewardEntry]) -> tuple[int, int]:
    before = len(load_existing_rewards(path))
    ordered = sorted(
        [entry.to_dict() for entry in entries],
        key=lambda item: (item["billing_month"], item["bank_name"], item["card_last_4"], item["reward_type"]),
    )

    with open(path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2)
        f.write("\n")

    return before, len(ordered)


def main() -> None:
    args = parse_args()
    statements_dir = resolve_statements_dir()
    rewards_file = statements_dir / "rewards_history.json"

    entries, warnings = collect_entries(statements_dir)

    print(f"Collected {len(entries)} reward entries.")
    if warnings:
        print(f"Warnings: {len(warnings)}")
        for warning in warnings[:20]:
            print(f"  - {warning}")
        if len(warnings) > 20:
            print(f"  ... {len(warnings) - 20} more warnings")

    if args.dry_run:
        print("Dry run only. rewards_history.json not written.")
        return

    before, after = write_rewards(rewards_file, entries)
    print(f"Wrote {rewards_file}")
    print(f"Entries before: {before}")
    print(f"Entries after: {after}")


if __name__ == "__main__":
    main()
