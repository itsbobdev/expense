"""Add manual bill type

Revision ID: 008
Revises: 007
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manual_bills",
        sa.Column(
            "manual_type",
            sa.String(),
            nullable=False,
            server_default="recurring",
        ),
    )
    op.execute(
        """
        UPDATE manual_bills
        SET manual_type = 'recurring'
        WHERE manual_type IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("manual_bills", "manual_type")
