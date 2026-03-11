from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_review_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """
    Create inline keyboard for transaction review.

    Args:
        transaction_id: ID of the transaction being reviewed

    Returns:
        InlineKeyboardMarkup with assignment buttons
    """
    keyboard = [
        [
            InlineKeyboardButton("👨 Parent", callback_data=f"assign_{transaction_id}_parent"),
            InlineKeyboardButton("👫 Spouse", callback_data=f"assign_{transaction_id}_spouse"),
        ],
        [
            InlineKeyboardButton("👤 Self", callback_data=f"assign_{transaction_id}_self"),
            InlineKeyboardButton("❌ Skip", callback_data=f"skip_{transaction_id}"),
        ],
    ]
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
