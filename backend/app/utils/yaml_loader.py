"""
YAML Loader for Statement-People Identifier

Parses the YAML configuration file to extract person and card mappings.
"""
import yaml
from pathlib import Path
from typing import List, Dict, Optional


def load_person_card_mappings(
    yaml_path: str = "statements/statement_people_identifier.yaml"
) -> List[Dict]:
    """
    Parse YAML file and return list of persons with their cards.

    Args:
        yaml_path: Path to the YAML configuration file

    Returns:
        List of dictionaries with format:
        [
            {
                "name": "foo_wah_liang",
                "cards": ["9103", "0104", "4474", "5441", "8335"]
            },
            ...
        ]

    Raises:
        FileNotFoundError: If YAML file doesn't exist
        ValueError: If YAML format is invalid
    """
    yaml_file = Path(yaml_path)

    if not yaml_file.exists():
        raise FileNotFoundError(
            f"YAML configuration file not found: {yaml_path}\n"
            f"Please create the file with person and card mappings.\n"
            f"See README.md for the expected format."
        )

    with open(yaml_file, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    people = []
    for entry in data.get("people", []):
        name = entry.get("name")
        if not name:
            continue

        cards = []
        # Extract card last-4 from nested bank -> card_product -> last4
        for bank_name, bank_cards in entry.get("cards", {}).items():
            if not isinstance(bank_cards, dict):
                continue
            for card_product, last4 in bank_cards.items():
                last4_str = str(last4).strip().strip('"')
                # Always take rightmost 4 digits (handles Amex 5-digit segments)
                if len(last4_str) >= 4:
                    cards.append(last4_str[-4:])

        # Also extract former cards
        for bank_name, bank_cards in entry.get("former_cards", {}).items():
            if not isinstance(bank_cards, dict):
                continue
            for card_product, card_info in bank_cards.items():
                if isinstance(card_info, dict):
                    last4_str = str(card_info.get("last4", "")).strip().strip('"')
                    if len(last4_str) >= 4:
                        cards.append(last4_str[-4:])

        people.append({"name": name, "cards": cards})

    if not people:
        raise ValueError(
            f"No valid person entries found in {yaml_path}\n"
            f"Please check the YAML format."
        )

    return people


def get_initial_blacklist_categories() -> List[Dict]:
    """
    Return the initial blacklist categories to seed in the database.

    Returns:
        List of dictionaries with format:
        [
            {
                "name": "flights",
                "keywords": ["jetstar", "scoot", ...],
                "is_active": True
            },
            ...
        ]
    """
    return [
        {
            "name": "flights",
            "keywords": [
                "jetstar",
                "scoot",
                "changi airport",
                "airline",
                "airways",
                "singapore air",
                "sia",
                "air asia",
                "emirates",
                "qatar airways",
                "cathay pacific",
                "airasia",
                "budget aviation",
            ],
            "is_active": True,
        },
        {
            "name": "tours",
            "keywords": [
                "tour",
                "klook",
                "pelago",
                "chan brothers",
                "travel agency",
                "trip.com",
                "ctrip",
                "expedia",
                "agoda tour",
                "viator",
            ],
            "is_active": True,
        },
        {
            "name": "accommodation",
            "keywords": [
                "airbnb",
                "booking.com",
                "agoda",
                "hotel",
                "hostel",
                "homestay",
                "resort",
                "marriott",
                "hilton",
                "hyatt",
                "serviced apartment",
            ],
            "is_active": True,
        },
        {
            "name": "foreign_currency",
            "keywords": [
                "ccy conversion",
                "foreign exchange",
                "fx fee",
                "currency conversion",
                "forex",
            ],
            "is_active": True,
        },
        {
            "name": "amaze",
            "keywords": [
                "amaze*",
                "amaze ",
            ],
            "is_active": True,
        },
        {
            "name": "atome",
            "keywords": [
                "atome*",
                "atome ",
            ],
            "is_active": True,
        },
    ]
