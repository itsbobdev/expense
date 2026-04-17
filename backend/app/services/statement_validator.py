from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pdfplumber


MONTH_ABBREVIATIONS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

UOB_TXN_LINE_RE = re.compile(
    r"^(?P<post_day>\d{2}) (?P<post_month>[A-Z]{3}) "
    r"(?P<txn_day>\d{2}) (?P<txn_month>[A-Z]{3}) "
    r"(?P<description>.+?) (?P<amount>[\d,]+\.\d{2})(?P<credit>CR)?$"
)
UOB_REWARD_PATTERNS = (
    re.compile(r"^UOB EVOL Card Cashback", re.IGNORECASE),
    re.compile(r"^UOB Absolute Cashback", re.IGNORECASE),
)
COMMON_REWARD_PATTERNS = (
    re.compile(r"^\d+%\s*CASHBACK$", re.IGNORECASE),
    re.compile(r"^OTHER\s+CASHBACK$", re.IGNORECASE),
)
UOB_PAYMENT_HINTS = ("PAYMT", "PAYMENT")
REFUND_MATCH_STOP_WORDS = {
    "CR",
    "CB",
    "DISPUTES",
    "DISPUTE",
    "CREDIT",
    "REFUND",
    "REVERSAL",
    "REV",
}


class StatementValidationError(ValueError):
    """Raised when extracted statement JSON is internally inconsistent."""


def validate_statement_json(data: dict, json_path: Path) -> None:
    if _should_validate_subtotal(data):
        _validate_statement_subtotal(data)

    if _is_uob_credit_card_statement(data):
        _validate_uob_credit_rows(data, json_path)


def _should_validate_subtotal(data: dict) -> bool:
    if data.get("account_number_last_4") or data.get("account_name"):
        return False
    if (data.get("bank_name") or "").upper() == "UOB":
        # UOB card SUB TOTAL includes carried balances, so transaction-only JSON
        # cannot be validated against it without parsing prior-cycle balances.
        return False
    total_charges = data.get("total_charges")
    transactions = data.get("transactions") or []
    return total_charges is not None and bool(transactions)


def _validate_statement_subtotal(data: dict) -> None:
    expected_total = round(float(data.get("total_charges") or 0.0), 2)
    actual_total = round(sum(_statement_contribution(txn) for txn in data.get("transactions") or []), 2)
    if abs(actual_total - expected_total) > 0.01:
        raise StatementValidationError(
            f"Statement subtotal mismatch: transactions contribute {actual_total:.2f} but total_charges is {expected_total:.2f}"
        )


def _statement_contribution(txn: dict) -> float:
    amount = float(txn.get("amount", 0.0) or 0.0)
    merchant_name = txn.get("merchant_name") or txn.get("description") or ""
    reward_patterns = (*UOB_REWARD_PATTERNS, *COMMON_REWARD_PATTERNS)
    is_reward = bool(txn.get("is_reward")) or any(pattern.match(merchant_name) for pattern in reward_patterns)
    contribution = -abs(amount) if is_reward else amount
    ccy_fee = txn.get("ccy_fee")
    if ccy_fee is not None:
        contribution += abs(float(ccy_fee))
    return contribution


def _is_uob_credit_card_statement(data: dict) -> bool:
    return (
        (data.get("bank_name") or "").upper() == "UOB"
        and not (data.get("account_number_last_4") or data.get("account_name"))
        and bool(data.get("card_last_4"))
        and bool(data.get("statement_date"))
    )


def _validate_uob_credit_rows(data: dict, json_path: Path) -> None:
    pdf_filename = data.get("filename")
    if not pdf_filename or Path(str(pdf_filename)).suffix.lower() != ".pdf":
        return

    pdf_path = json_path.with_name(pdf_filename)
    if not pdf_path.exists():
        return

    expected_rows = _extract_uob_credit_rows(
        pdf_path=pdf_path,
        card_last_4=str(data.get("card_last_4") or ""),
        statement_date=date.fromisoformat(data["statement_date"]),
    )
    if not expected_rows:
        return

    remaining = list(data.get("transactions") or [])
    missing_rows: list[str] = []

    for row in expected_rows:
        matched_index = _find_matching_transaction_index(remaining, row)
        if matched_index is None:
            post_date, txn_date, description, amount, expected_kind = row
            missing_rows.append(
                f"post={post_date.isoformat()} txn={txn_date.isoformat()} {description} {amount:.2f} {expected_kind}"
            )
            continue
        remaining.pop(matched_index)

    if missing_rows:
        raise StatementValidationError(
            "Missing UOB credit rows from statement JSON: " + "; ".join(missing_rows)
        )


def _extract_uob_credit_rows(
    pdf_path: Path,
    card_last_4: str,
    statement_date: date,
) -> list[tuple[date, date, str, float, str]]:
    rows: list[tuple[date, date, str, float, str]] = []
    in_section = False

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            lines = (page.extract_text() or "").splitlines()
            for index, line in enumerate(lines):
                if not in_section and _is_uob_card_section_header(lines, index, card_last_4):
                    in_section = True
                    continue

                if not in_section:
                    continue

                stripped = line.strip()
                if stripped.startswith("SUB TOTAL") or stripped.startswith("TOTAL BALANCE FOR"):
                    in_section = False
                    continue

                match = UOB_TXN_LINE_RE.match(stripped)
                if not match or not match.group("credit"):
                    continue

                description = match.group("description").strip()
                if any(hint in description.upper() for hint in UOB_PAYMENT_HINTS):
                    continue

                post_date = _infer_uob_transaction_date(
                    match.group("post_day"),
                    match.group("post_month"),
                    statement_date,
                )
                txn_date = _infer_uob_transaction_date(
                    match.group("txn_day"),
                    match.group("txn_month"),
                    statement_date,
                )
                amount = float(match.group("amount").replace(",", ""))
                expected_kind = "reward" if _is_uob_reward_line(description) else "refund"
                rows.append((post_date, txn_date, description, amount, expected_kind))

    return rows


def _is_uob_card_section_header(lines: list[str], index: int, card_last_4: str) -> bool:
    line = lines[index]
    digits = re.sub(r"[^0-9]", "", line)
    if not digits.endswith(card_last_4):
        return False
    return any("Post Trans" in candidate for candidate in lines[index : index + 4])


def _infer_uob_transaction_date(day_text: str, month_text: str, statement_date: date) -> date:
    month = MONTH_ABBREVIATIONS[month_text]
    year = statement_date.year - (1 if month > statement_date.month else 0)
    return date(year, month, int(day_text))


def _is_uob_reward_line(description: str) -> bool:
    return any(pattern.match(description) for pattern in UOB_REWARD_PATTERNS)


def _find_matching_transaction_index(
    transactions: list[dict],
    row: tuple[date, date, str, float, str],
) -> int | None:
    for idx, txn in enumerate(transactions):
        if _transaction_matches_uob_credit_row(txn, row):
            return idx
    return None


def _transaction_matches_uob_credit_row(
    txn: dict,
    row: tuple[date, date, str, float, str],
) -> bool:
    post_date, txn_date, description, amount, expected_kind = row
    if txn.get("transaction_date") not in {post_date.isoformat(), txn_date.isoformat()}:
        return False

    txn_amount = float(txn.get("amount", 0.0) or 0.0)
    if expected_kind == "reward":
        if not bool(txn.get("is_reward")):
            return False
        if abs(abs(txn_amount) - amount) > 0.01:
            return False
    else:
        if not bool(txn.get("is_refund")) or txn_amount >= 0:
            return False
        if abs(abs(txn_amount) - amount) > 0.01:
            return False

    candidate = " ".join(filter(None, [txn.get("merchant_name"), txn.get("raw_description")]))
    normalized_expected = _normalized_refund_text(description)
    normalized_candidate = _normalized_refund_text(candidate)
    return bool(normalized_expected) and normalized_expected in normalized_candidate


def _normalized_refund_text(value: str | None) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", " ", (value or "").upper()).strip()
    tokens = [token for token in cleaned.split() if token not in REFUND_MATCH_STOP_WORDS]
    return " ".join(tokens)
