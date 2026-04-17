"""Persist account transaction type for alert classification

Revision ID: 010
Revises: 009
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("transaction_type", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "transaction_type")
