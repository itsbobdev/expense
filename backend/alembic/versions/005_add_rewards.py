"""Add is_reward/reward_type to transactions and create card_rewards table

Revision ID: 005
Revises: 004
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add reward columns to transactions
    op.add_column('transactions', sa.Column('is_reward', sa.Boolean(), nullable=True))
    op.add_column('transactions', sa.Column('reward_type', sa.String(), nullable=True))

    # Create card_rewards table
    op.create_table(
        'card_rewards',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('statement_id', sa.Integer(), sa.ForeignKey('statements.id'), nullable=True),
        sa.Column('billing_month', sa.String(), nullable=False),
        sa.Column('card_last_4', sa.String(4), nullable=True),
        sa.Column('bank_name', sa.String(), nullable=True),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('persons.id'), nullable=True),
        sa.Column('reward_type', sa.String(), nullable=False),
        sa.Column('earned_this_period', sa.Float(), nullable=False),
        sa.Column('balance', sa.Float(), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_card_rewards_billing_month', 'card_rewards', ['billing_month'])

    # Data migration: fix already-imported cashback transactions
    # SQLite does not support regexp in standard SQL, so we use LIKE patterns
    op.execute("""
        UPDATE transactions
        SET is_reward = 1,
            reward_type = 'cashback',
            is_refund = 0,
            needs_review = 0
        WHERE merchant_name LIKE '%CASHBACK%'
           OR merchant_name LIKE 'UOB EVOL Card Cashback%'
           OR merchant_name LIKE 'UOB Absolute Cashback%'
    """)


def downgrade() -> None:
    op.drop_index('ix_card_rewards_billing_month', 'card_rewards')
    op.drop_table('card_rewards')
    op.drop_column('transactions', 'reward_type')
    op.drop_column('transactions', 'is_reward')
