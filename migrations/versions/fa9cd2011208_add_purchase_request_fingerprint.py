"""add purchase request fingerprint

Revision ID: fa9cd2011208
Revises: deef914b2524
Create Date: 2026-11-06 12:05:07.537447

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa9cd2011208'
down_revision: Union[str, Sequence[str], None] = 'deef914b2524'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add purchase request fingerprint."""
    op.add_column(
        "wallet_transactions",
        sa.Column(
            "request_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove purchase request fingerprint."""
    op.drop_column(
        "wallet_transactions",
        "request_fingerprint",
    )