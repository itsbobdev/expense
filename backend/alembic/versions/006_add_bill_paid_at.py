"""Add paid_at to bills

Revision ID: 006
Revises: 005
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bills', sa.Column('paid_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('bills', 'paid_at')
