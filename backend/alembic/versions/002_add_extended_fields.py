"""Add extended fields to statements and transactions

Revision ID: 002
Revises: 001
Create Date: 2026-03-13

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to statements table
    op.add_column('statements', sa.Column('bank_name', sa.String(), nullable=True))
    op.add_column('statements', sa.Column('card_name', sa.String(), nullable=True))
    op.add_column('statements', sa.Column('period_start', sa.Date(), nullable=True))
    op.add_column('statements', sa.Column('period_end', sa.Date(), nullable=True))
    op.add_column('statements', sa.Column('pdf_hash', sa.String(64), nullable=True))
    op.add_column('statements', sa.Column('total_charges', sa.Float(), nullable=True))
    op.create_unique_constraint('uq_statements_pdf_hash', 'statements', ['pdf_hash'])

    # Add new columns to transactions table
    op.add_column('transactions', sa.Column('raw_description', sa.String(), nullable=True))
    op.add_column('transactions', sa.Column('ccy_fee', sa.Float(), nullable=True))
    op.add_column('transactions', sa.Column('country_code', sa.String(2), nullable=True))
    op.add_column('transactions', sa.Column('location', sa.String(), nullable=True))


def downgrade():
    # Remove columns from transactions table
    op.drop_column('transactions', 'location')
    op.drop_column('transactions', 'country_code')
    op.drop_column('transactions', 'ccy_fee')
    op.drop_column('transactions', 'raw_description')

    # Remove columns from statements table
    op.drop_constraint('uq_statements_pdf_hash', 'statements', type_='unique')
    op.drop_column('statements', 'total_charges')
    op.drop_column('statements', 'pdf_hash')
    op.drop_column('statements', 'period_end')
    op.drop_column('statements', 'period_start')
    op.drop_column('statements', 'card_name')
    op.drop_column('statements', 'bank_name')
