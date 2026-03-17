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
        content = f.read()

    # Parse YAML (handles multiple documents with same 'name' key)
    people = []
    current_person = None

    for line in content.split('\n'):
        line = line.strip()

        if line.startswith('name:'):
            # Save previous person if exists
            if current_person:
                people.append(current_person)

            # Start new person
            name = line.split('name:')[1].strip()
            current_person = {"name": name, "cards": []}

        elif ':' in line and current_person:
            # Extract card last 4 digits (format: "- card_name: 1234")
            parts = line.split(':')
            if len(parts) == 2:
                card_digits = parts[1].strip()
                # Validate it's a 4-digit card number
                if card_digits.isdigit() and len(card_digits) == 4:
                    current_person["cards"].append(card_digits)

    # Don't forget the last person
    if current_person:
        people.append(current_person)

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
    ]
