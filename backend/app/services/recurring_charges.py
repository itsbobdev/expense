"""
Recurring Charges Service

Loads monthly recurring charges from YAML config and creates ManualBill
records for each billing month.
"""
import logging
from pathlib import Path
from typing import List, Dict, Optional

import yaml
from sqlalchemy.orm import Session

from app.models import Person, ManualBill
from app.config import settings

logger = logging.getLogger(__name__)


class RecurringChargesService:
    """Manages monthly recurring charges from YAML configuration."""

    def __init__(self, db: Session):
        self.db = db

    def load_config(self) -> List[Dict]:
        """
        Load recurring charges from monthly_payment_to_me.yaml.

        Returns:
            List of dicts with person name and their items.
        """
        yaml_path = settings.statements_dir / "monthly_payment_to_me.yaml"
        if not yaml_path.exists():
            logger.warning("Recurring charges YAML not found: %s", yaml_path)
            return []

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return data.get("people", [])

    def generate_recurring_bills(self, billing_month: str) -> List[ManualBill]:
        """
        Create ManualBill records for all active recurring charges in a billing month.

        Idempotent: skips items that already have a ManualBill for this month.

        Args:
            billing_month: Format "YYYY-MM"

        Returns:
            List of newly created ManualBill records
        """
        config = self.load_config()
        created = []

        for person_config in config:
            person_name = person_config.get("name")
            person = self.db.query(Person).filter(Person.name == person_name).first()
            if not person:
                logger.warning("Person '%s' not found in DB, skipping recurring charges", person_name)
                continue

            items = person_config.get("items", {})
            for item_key, item in items.items():
                # Check effective date range
                effective_from = item.get("effective_from")
                effective_until = item.get("effective_until")

                if effective_from and billing_month < effective_from:
                    continue
                if effective_until and billing_month > effective_until:
                    continue

                description = item.get("description", item_key)
                amount = item.get("amount", 0.0)

                # Check for existing (idempotent)
                existing = self.db.query(ManualBill).filter(
                    ManualBill.person_id == person.id,
                    ManualBill.description == description,
                    ManualBill.billing_month == billing_month,
                    ManualBill.manual_type == ManualBill.TYPE_RECURRING,
                ).first()

                if existing:
                    continue

                manual_bill = ManualBill(
                    person_id=person.id,
                    amount=amount,
                    description=description,
                    billing_month=billing_month,
                    manual_type=ManualBill.TYPE_RECURRING,
                )
                self.db.add(manual_bill)
                created.append(manual_bill)

        if created:
            self.db.commit()
            logger.info("Created %d recurring charge(s) for %s", len(created), billing_month)

        return created
