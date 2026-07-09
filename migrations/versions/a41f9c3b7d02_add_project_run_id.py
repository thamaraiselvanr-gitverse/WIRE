"""add projects.run_id for per-project run isolation

Revision ID: a41f9c3b7d02
Revises: cfc8461062df
Create Date: 2026-07-08 09:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a41f9c3b7d02"
down_revision: Union[str, Sequence[str], None] = "cfc8461062df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the per-project run-directory name.

    Nullable: rows created before this column existed keep their legacy
    domain-derived run directories (the API falls back to that naming when
    run_id is NULL).
    """
    op.add_column("projects", sa.Column("run_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "run_id")
