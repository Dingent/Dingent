"""add user identities

Revision ID: 20260525_user_identity
Revises: 890659c554b6
Create Date: 2026-05-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260525_user_identity"
down_revision: str | Sequence[str] | None = "890659c554b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "useridentity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_subject", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("raw_profile", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_subject", name="unique_provider_subject"),
    )
    op.create_index(op.f("ix_useridentity_id"), "useridentity", ["id"], unique=False)
    op.create_index(op.f("ix_useridentity_user_id"), "useridentity", ["user_id"], unique=False)
    op.create_index(op.f("ix_useridentity_provider"), "useridentity", ["provider"], unique=False)
    op.create_index(op.f("ix_useridentity_provider_subject"), "useridentity", ["provider_subject"], unique=False)
    op.create_index(op.f("ix_useridentity_email"), "useridentity", ["email"], unique=False)
    op.alter_column("user", "hashed_password", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.alter_column("user", "hashed_password", existing_type=sa.String(), nullable=False)
    op.drop_index(op.f("ix_useridentity_email"), table_name="useridentity")
    op.drop_index(op.f("ix_useridentity_provider_subject"), table_name="useridentity")
    op.drop_index(op.f("ix_useridentity_provider"), table_name="useridentity")
    op.drop_index(op.f("ix_useridentity_user_id"), table_name="useridentity")
    op.drop_index(op.f("ix_useridentity_id"), table_name="useridentity")
    op.drop_table("useridentity")
