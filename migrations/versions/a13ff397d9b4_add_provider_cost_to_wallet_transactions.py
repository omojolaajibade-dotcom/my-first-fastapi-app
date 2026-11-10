"""add provider cost to wallet transactions

Revision ID: a13ff397d9b4
Revises: fa9cd2011208
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a13ff397d9b4'
down_revision: Union[str, Sequence[str], None] = 'fa9cd2011208'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wallet_transactions",
        sa.Column(
            "provider_cost",
            sa.Numeric(12, 2),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "wallet_transactions",
        "provider_cost",
    )