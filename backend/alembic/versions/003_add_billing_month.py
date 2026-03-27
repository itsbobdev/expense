"""Add billing_month to statements and transactions

Revision ID: 003
Revises: 002
Create Date: 2026-03-17

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('statements', sa.Column('billing_month', sa.String(), nullable=True))
    op.create_index('ix_statements_billing_month', 'statements', ['billing_month'])

    op.add_column('transactions', sa.Column('billing_month', sa.String(), nullable=True))
    op.create_index('ix_transactions_billing_month', 'transactions', ['billing_month'])

    # Add categories column to transactions (JSON array from extraction)
    op.add_column('transactions', sa.Column('categories', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('transactions', 'categories')
    op.drop_index('ix_transactions_billing_month', 'transactions')
    op.drop_column('transactions', 'billing_month')
    op.drop_index('ix_statements_billing_month', 'statements')
    op.drop_column('statements', 'billing_month')
