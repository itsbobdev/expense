"""Add blacklist_categories and manual_bills tables

Revision ID: 001
Revises:
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create blacklist_categories table
    op.create_table(
        'blacklist_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('keywords', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='1'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_blacklist_categories_id'), 'blacklist_categories', ['id'], unique=False)
    op.create_index(op.f('ix_blacklist_categories_name'), 'blacklist_categories', ['name'], unique=True)

    # Create manual_bills table
    op.create_table(
        'manual_bills',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('person_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('billing_month', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['person_id'], ['persons.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_manual_bills_id'), 'manual_bills', ['id'], unique=False)
    op.create_index(op.f('ix_manual_bills_billing_month'), 'manual_bills', ['billing_month'], unique=False)

    # Add is_auto_created column to persons table
    op.add_column('persons', sa.Column('is_auto_created', sa.Boolean(), nullable=True, server_default='0'))

    # Add blacklist_category_id to transactions table
    op.add_column('transactions', sa.Column('blacklist_category_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_transactions_blacklist_category_id', 'transactions', 'blacklist_categories', ['blacklist_category_id'], ['id'])

    # Update BillLineItem to support manual bills
    # Make transaction_id nullable
    op.alter_column('bill_line_items', 'transaction_id', nullable=True)

    # Add manual_bill_id column
    op.add_column('bill_line_items', sa.Column('manual_bill_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_bill_line_items_manual_bill_id', 'bill_line_items', 'manual_bills', ['manual_bill_id'], ['id'])


def downgrade():
    # Drop foreign keys and columns from bill_line_items
    op.drop_constraint('fk_bill_line_items_manual_bill_id', 'bill_line_items', type_='foreignkey')
    op.drop_column('bill_line_items', 'manual_bill_id')
    op.alter_column('bill_line_items', 'transaction_id', nullable=False)

    # Drop blacklist_category_id from transactions
    op.drop_constraint('fk_transactions_blacklist_category_id', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'blacklist_category_id')

    # Drop is_auto_created from persons
    op.drop_column('persons', 'is_auto_created')

    # Drop manual_bills table
    op.drop_index(op.f('ix_manual_bills_billing_month'), table_name='manual_bills')
    op.drop_index(op.f('ix_manual_bills_id'), table_name='manual_bills')
    op.drop_table('manual_bills')

    # Drop blacklist_categories table
    op.drop_index(op.f('ix_blacklist_categories_name'), table_name='blacklist_categories')
    op.drop_index(op.f('ix_blacklist_categories_id'), table_name='blacklist_categories')
    op.drop_table('blacklist_categories')
