"""Persist the Discord message used by the player controls."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_player_messages"
down_revision = "0005_conversation_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_messages",
        sa.Column("guild_id", sa.BigInteger(), primary_key=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("player_messages")
