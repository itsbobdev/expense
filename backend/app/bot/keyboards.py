from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List
from app.models import Person, Transaction


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

    # Add "Skip" button in the last row
    keyboard.append([
        InlineKeyboardButton("Shared expense", callback_data=f"share_{transaction_id}"),
        InlineKeyboardButton("Skip", callback_data=f"skip_{transaction_id}"),
    ])

    return InlineKeyboardMarkup(keyboard)


def get_review_result_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Undo", callback_data=f"undo_{transaction_id}")],
    ])


def get_shared_expense_keyboard(
    transaction_id: int,
    persons: List[Person],
    selected_person_ids: List[int],
) -> InlineKeyboardMarkup:
    keyboard = []
    selected_set = set(selected_person_ids)

    person_buttons = [
        InlineKeyboardButton(
            f"{'✓ ' if person.id in selected_set else ''}{person.name}",
            callback_data=f"sharetoggle_{transaction_id}_{person.id}",
        )
        for person in persons
    ]

    for i in range(0, len(person_buttons), 2):
        keyboard.append(person_buttons[i:i+2])

    keyboard.append([
        InlineKeyboardButton("Equal split", callback_data=f"sharesave_{transaction_id}"),
        InlineKeyboardButton("Cancel", callback_data=f"sharecancel_{transaction_id}"),
    ])

    return InlineKeyboardMarkup(keyboard)


def get_refund_review_keyboard(
    refund_id: int,
    candidates: List[Transaction],
    persons: List[Person],
) -> InlineKeyboardMarkup:
    """
    Create inline keyboard for refund review.

    Shows candidate matches (from broad search), plus Search/Assign/Skip actions.
    """
    keyboard = []

    if candidates:
        # Show candidate originals (limit to 5 to avoid cluttering)
        for c in candidates[:5]:
            person_name = c.assigned_person.name if c.assigned_person else "unassigned"
            label = f"{c.transaction_date} {c.merchant_name} ${c.amount:.2f} ({person_name})"
            # Truncate label for Telegram button limit (64 bytes)
            if len(label) > 60:
                label = label[:57] + "..."
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"refmatch_{refund_id}_{c.id}")
            ])

    # Action row: Search by amount + Assign to person + Skip
    action_row = [
        InlineKeyboardButton("Search by amount", callback_data=f"refsearch_{refund_id}"),
        InlineKeyboardButton("Assign to person", callback_data=f"refassign_{refund_id}"),
    ]
    keyboard.append(action_row)

    keyboard.append([
        InlineKeyboardButton("Skip", callback_data=f"skip_{refund_id}"),
    ])

    return InlineKeyboardMarkup(keyboard)


def get_refund_person_keyboard(refund_id: int, persons: List[Person]) -> InlineKeyboardMarkup:
    """Person assignment keyboard for orphan refunds (cashback credits etc)."""
    keyboard = []
    person_buttons = [
        InlineKeyboardButton(
            p.name,
            callback_data=f"assign_{refund_id}_{p.id}"
        )
        for p in persons
    ]
    for i in range(0, len(person_buttons), 2):
        keyboard.append(person_buttons[i:i+2])

    keyboard.append([
        InlineKeyboardButton("Skip", callback_data=f"skip_{refund_id}"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_add_expense_person_keyboard(persons: List[Person]) -> InlineKeyboardMarkup:
    """Person picker for guided manual expense entry."""
    keyboard = []
    person_buttons = [
        InlineKeyboardButton(
            person.name,
            callback_data=f"addexpense_person_{person.id}",
        )
        for person in persons
    ]

    for i in range(0, len(person_buttons), 2):
        keyboard.append(person_buttons[i:i+2])

    keyboard.append([
        InlineKeyboardButton("Cancel", callback_data="addexpense_cancel"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_alert_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """Keyboard for active alert items shown in /alerts."""
    keyboard = [[
        InlineKeyboardButton("Resolve", callback_data=f"resolve_{transaction_id}"),
    ]]
    return InlineKeyboardMarkup(keyboard)


def get_resolved_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """Keyboard for resolved items: move back into /alerts."""
    keyboard = [[
        InlineKeyboardButton("Mark Unresolved", callback_data=f"unresolve_{transaction_id}"),
    ]]
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
            InlineKeyboardButton("Yes", callback_data=f"confirm_{action}_{item_id}"),
            InlineKeyboardButton("No", callback_data=f"cancel_{action}_{item_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_bill_keyboard(
    bill_id: int,
    status: str,
    can_finalize: bool,
    manually_added_items: List[tuple[int, str]] | None = None,
) -> InlineKeyboardMarkup | None:
    """Keyboard for bill state transitions and manual item removal."""
    keyboard = []

    if status == "draft":
        if can_finalize:
            keyboard.append([
                InlineKeyboardButton("Finalize", callback_data=f"bill_finalize_{bill_id}"),
            ])

        for manual_bill_id, description in manually_added_items or []:
            label = f"Remove: {description}"
            if len(label) > 30:
                label = label[:27] + "..."
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"bill_remove_{bill_id}_{manual_bill_id}"),
            ])
    elif status == "finalized":
        keyboard.append([
            InlineKeyboardButton("Mark paid", callback_data=f"bill_pay_{bill_id}"),
        ])
    elif status == "paid":
        keyboard.append([
            InlineKeyboardButton("Mark unpaid", callback_data=f"bill_unpay_{bill_id}"),
        ])

    if not keyboard:
        return None

    return InlineKeyboardMarkup(keyboard)
