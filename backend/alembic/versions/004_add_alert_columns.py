"""Add alert_status, parent_transaction_id, resolved_by_transaction_id, resolved_method to transactions

Revision ID: 004
Revises: 003
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite does not support adding FK constraints via ALTER TABLE —
    # columns are added as plain integers; FK relationships are enforced at the ORM level.
    op.add_column('transactions', sa.Column('alert_status', sa.String(), nullable=True))
    op.add_column('transactions', sa.Column('parent_transaction_id', sa.Integer(), nullable=True))
    op.add_column('transactions', sa.Column('resolved_by_transaction_id', sa.Integer(), nullable=True))
    op.add_column('transactions', sa.Column('resolved_method', sa.String(), nullable=True))
    op.create_index('ix_transactions_alert_status', 'transactions', ['alert_status'])


def downgrade() -> None:
    op.drop_index('ix_transactions_alert_status', 'transactions')
    op.drop_column('transactions', 'resolved_method')
    op.drop_column('transactions', 'resolved_by_transaction_id')
    op.drop_column('transactions', 'parent_transaction_id')
    op.drop_column('transactions', 'alert_status')
