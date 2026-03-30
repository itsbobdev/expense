from dataclasses import dataclass
import json

from sqlalchemy.orm import Session

from app.models import AssignmentRule, Person
from app.utils.yaml_loader import load_person_card_mappings


@dataclass
class CardRuleSyncResult:
    updated_people: int
    created_rules: int
    retargeted_rules: int
    disabled_rules: int


def sync_card_direct_rules(db: Session) -> CardRuleSyncResult:
    people_data = load_person_card_mappings()
    persons = {person.name: person for person in db.query(Person).all()}

    updated_people = 0
    created_rules = 0
    retargeted_rules = 0
    disabled_rules = 0

    for person_data in people_data:
        person = persons.get(person_data["name"])
        if not person:
            continue

        yaml_cards = sorted(set(person_data["cards"]))
        existing_cards = sorted(set(person.card_last_4_digits or []))
        if existing_cards != yaml_cards:
            person.card_last_4_digits = yaml_cards
            updated_people += 1

        for card_last_4 in yaml_cards:
            rules = (
                db.query(AssignmentRule)
                .filter(
                    AssignmentRule.rule_type == "card_direct",
                )
                .order_by(AssignmentRule.id)
                .all()
            )
            rules = [
                rule for rule in rules
                if _extract_card_last_4(rule.conditions) == card_last_4
            ]

            if not rules:
                db.add(
                    AssignmentRule(
                        priority=100,
                        rule_type="card_direct",
                        conditions={"card_last_4": card_last_4},
                        assign_to_person_id=person.id,
                        is_active=True,
                    )
                )
                created_rules += 1
                continue

            primary_rule = rules[0]
            if primary_rule.assign_to_person_id != person.id:
                primary_rule.assign_to_person_id = person.id
                retargeted_rules += 1
            if not primary_rule.is_active:
                primary_rule.is_active = True

            for duplicate_rule in rules[1:]:
                if duplicate_rule.is_active:
                    duplicate_rule.is_active = False
                    disabled_rules += 1

    db.commit()
    return CardRuleSyncResult(
        updated_people=updated_people,
        created_rules=created_rules,
        retargeted_rules=retargeted_rules,
        disabled_rules=disabled_rules,
    )


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
