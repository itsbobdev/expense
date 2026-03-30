import re
import json

from sqlalchemy.orm import Session

from app.models import AssignmentRule, Person, Statement


def get_card_owner_name(db: Session, statement: Statement | None) -> str | None:
    """Resolve the configured owner for a card via card_direct assignment rules."""
    if not statement or not statement.card_last_4:
        return None

    rule = (
        db.query(AssignmentRule)
        .join(Person, Person.id == AssignmentRule.assign_to_person_id)
        .filter(
            AssignmentRule.is_active == True,
            AssignmentRule.rule_type == "card_direct",
        )
        .all()
    )
    rule = next(
        (
            candidate
            for candidate in rule
            if _extract_card_last_4(candidate.conditions) == statement.card_last_4
        ),
        None,
    )

    if not rule or not rule.person:
        return None

    return rule.person.name


def format_statement_card_label(
    db: Session,
    statement: Statement | None,
    billed_person: Person | None = None,
) -> str:
    """Format the card suffix with bank, last-4 digits, and owner when useful."""
    if not statement:
        return ""

    bank_name = statement.bank_name or ""
    label = f"{bank_name} ****{statement.card_last_4}".strip()
    owner_name = get_card_owner_name(db, statement)
    if owner_name and not _is_same_person(owner_name, billed_person.name if billed_person else None):
        label = f"{label}, {owner_name} card"
    return f"  ({label})"


def _is_same_person(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    normalize = lambda value: re.sub(r"[-_\s]+", "", value).lower()
    return normalize(left) == normalize(right)


def _extract_card_last_4(conditions) -> str | None:
    if isinstance(conditions, dict):
        value = conditions.get("card_last_4")
        return str(value) if value is not None else None
    if isinstance(conditions, str):
        try:
            decoded = json.loads(conditions)
        except json.JSONDecodeError:
            return None
        value = decoded.get("card_last_4")
        return str(value) if value is not None else None
    return None
