
"""add Ridamsub transaction identifiers

Revision ID: deef914b2524
Revises: 12e02b4742e6
"""

from alembic import op
import sqlalchemy as sa

revision = "deef914b2524"
down_revision = "12e02b4742e6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "wallet_transactions",
        sa.Column("provider_transaction_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "wallet_transactions",
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
    )

    op.create_index(
        "ix_wallet_transactions_provider_transaction_id",
        "wallet_transactions",
        ["provider_transaction_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_wallet_transactions_provider_transaction_id",
        table_name="wallet_transactions",
    )
    op.drop_column("wallet_transactions", "idempotency_key")
    op.drop_column("wallet_transactions", "provider_transaction_id")
