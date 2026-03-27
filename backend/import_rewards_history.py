"""
Import rewards history from statements/rewards_history.json into card_rewards table.

Dedup key: (billing_month, card_last_4, reward_type)
Person lookup: assignment_rules by card_last_4, fall back to self person.

Usage:
    cd backend && python import_rewards_history.py
"""
import json
import sys
from pathlib import Path
from datetime import date

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal
from app.models import AssignmentRule, Person
from app.models.card_reward import CardReward
from app.config import settings


def parse_date(date_str):
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def lookup_person_id(db, card_last_4):
    rule = (
        db.query(AssignmentRule)
        .filter(
            AssignmentRule.is_active == True,
            AssignmentRule.rule_type == "card_direct",
        )
        .filter(AssignmentRule.conditions.contains({"card_last_4": card_last_4}))
        .first()
    )
    if rule:
        return rule.assign_to_person_id
    self_person = db.query(Person).filter(Person.relationship_type == "self").first()
    return self_person.id if self_person else None


def main():
    rewards_file = settings.statements_dir / "rewards_history.json"
    if not rewards_file.exists():
        print(f"Not found: {rewards_file}")
        sys.exit(1)

    with open(rewards_file, "r", encoding="utf-8") as f:
        entries = json.load(f)

    if not entries:
        print("rewards_history.json is empty — nothing to import.")
        return

    db = SessionLocal()
    try:
        inserted = 0
        skipped = 0

        for entry in entries:
            billing_month = entry.get("billing_month")
            card_last_4 = entry.get("card_last_4")
            reward_type = entry.get("reward_type")
            earned = entry.get("earned_this_period")

            if not all([billing_month, card_last_4, reward_type, earned is not None]):
                print(f"  Skipping incomplete entry: {entry}")
                skipped += 1
                continue

            # Dedup by (billing_month, card_last_4, reward_type)
            existing = (
                db.query(CardReward)
                .filter(
                    CardReward.billing_month == billing_month,
                    CardReward.card_last_4 == card_last_4,
                    CardReward.reward_type == reward_type,
                )
                .first()
            )
            if existing:
                skipped += 1
                continue

            person_id = lookup_person_id(db, card_last_4)

            reward = CardReward(
                statement_id=None,
                billing_month=billing_month,
                card_last_4=card_last_4,
                bank_name=entry.get("bank_name"),
                person_id=person_id,
                reward_type=reward_type,
                earned_this_period=earned,
                balance=entry.get("balance"),
                expiry_date=parse_date(entry.get("expiry_date")),
                description=entry.get("description"),
            )
            db.add(reward)
            inserted += 1

        db.commit()
        print(f"Done: {inserted} inserted, {skipped} skipped.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
