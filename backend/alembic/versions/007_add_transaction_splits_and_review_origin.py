"""Add transaction splits and review origin tracking

Revision ID: 007
Revises: 006
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("review_origin_method", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE transactions
        SET review_origin_method = assignment_method
        WHERE needs_review = 1
          AND review_origin_method IS NULL
          AND assignment_method IS NOT NULL
        """
    )

    op.create_table(
        "transaction_splits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("split_amount", sa.Float(), nullable=False),
        sa.Column("split_percent", sa.Float(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "transaction_id",
            "person_id",
            name="uq_transaction_splits_transaction_person",
        ),
    )
    op.create_index(
        op.f("ix_transaction_splits_id"),
        "transaction_splits",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transaction_splits_person_id"),
        "transaction_splits",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transaction_splits_transaction_id"),
        "transaction_splits",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_transaction_splits_transaction_id"), table_name="transaction_splits")
    op.drop_index(op.f("ix_transaction_splits_person_id"), table_name="transaction_splits")
    op.drop_index(op.f("ix_transaction_splits_id"), table_name="transaction_splits")
    op.drop_table("transaction_splits")
    op.drop_column("transactions", "review_origin_method")
