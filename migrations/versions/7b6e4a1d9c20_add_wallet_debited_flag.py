"""track whether purchase amounts have actually been debited

Revision ID: 7b6e4a1d9c20
Revises: 0c2a0a61359b
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b6e4a1d9c20"
down_revision: Union[str, Sequence[str], None] = "0c2a0a61359b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing purchase rows were debited at creation by the old application.
    # Keep that state for pending/success rows to prevent double charging or
    # missed refunds after deployment. Failed rows had already been refunded.
    op.add_column(
        "wallet_transactions",
        sa.Column(
            "wallet_debited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE wallet_transactions
            SET wallet_debited = CASE
                WHEN lower(status) IN ('pending', 'pending_requery', 'success')
                    THEN TRUE
                ELSE FALSE
            END
            WHERE transaction_type IN ('airtime_purchase', 'data_purchase')
            """
        )
    )


def downgrade() -> None:
    op.drop_column("wallet_transactions", "wallet_debited")
