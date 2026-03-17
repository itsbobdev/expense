from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List
from app.models import Person


def get_review_keyboard(transaction_id: int, persons: List[Person]) -> InlineKeyboardMarkup:
    """
    Create inline keyboard for transaction review with dynamic person buttons.

    Args:
        transaction_id: ID of the transaction being reviewed
        persons: List of Person objects to create buttons for

    Returns:
        InlineKeyboardMarkup with assignment buttons
    """
    keyboard = []

    # Create buttons for each person (2 per row)
    person_buttons = [
        InlineKeyboardButton(
            f"{person.name}",
            callback_data=f"assign_{transaction_id}_{person.id}"
        )
        for person in persons
    ]

    # Arrange in rows of 2
    for i in range(0, len(person_buttons), 2):
        row = person_buttons[i:i+2]
        keyboard.append(row)

    # Add "Add to blacklist" and "Skip" buttons in the last row
    keyboard.append([
        InlineKeyboardButton("📋 Add to blacklist", callback_data=f"add_blacklist_{transaction_id}"),
        InlineKeyboardButton("❌ Skip", callback_data=f"skip_{transaction_id}"),
    ])

    return InlineKeyboardMarkup(keyboard)


def get_confirmation_keyboard(action: str, item_id: int) -> InlineKeyboardMarkup:
    """
    Create confirmation keyboard for actions.

    Args:
        action: The action to confirm (e.g., 'delete', 'finalize')
        item_id: ID of the item

    Returns:
        InlineKeyboardMarkup with Yes/No buttons
    """
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"confirm_{action}_{item_id}"),
            InlineKeyboardButton("❌ No", callback_data=f"cancel_{action}_{item_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
