"""Persist bounded short-term agent conversation messages."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_conversation_messages"
down_revision = "0004_memory_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("thread_id", sa.String(256), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_conversation_messages_thread_id_id",
        "conversation_messages",
        ["thread_id", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_messages_thread_id_id",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
