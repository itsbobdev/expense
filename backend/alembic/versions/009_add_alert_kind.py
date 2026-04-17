"""Add alert kind for generalized alerts

Revision ID: 009
Revises: 008
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("alert_kind", sa.String(), nullable=True))
    op.create_index("ix_transactions_alert_kind", "transactions", ["alert_kind"])

    op.execute(
        """
        UPDATE transactions
        SET alert_kind = 'card_fee'
        WHERE alert_status IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE transactions
        SET alert_kind = 'high_value',
            alert_status = CASE
                WHEN alert_status IS NULL THEN 'pending'
                ELSE alert_status
            END
        WHERE alert_kind IS NULL
          AND COALESCE(is_reward, 0) = 0
          AND parent_transaction_id IS NULL
          AND ABS(amount) > 111
        """
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_alert_kind", table_name="transactions")
    op.drop_column("transactions", "alert_kind")
