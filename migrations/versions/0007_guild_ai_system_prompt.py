"""Persist the per-guild AI system prompt."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_guild_ai_system_prompt"
down_revision = "0006_player_messages"
branch_labels = None
depends_on = None


_DEFAULT_PROMPT = (
    "You are PeaceMusic, a helpful and friendly Discord music assistant. "
    "Be concise, clear, and respectful. Use available tools when needed, "
    "and never claim an action succeeded unless a tool confirms it."
)


def upgrade() -> None:
    op.add_column(
        "guild_settings",
        sa.Column(
            "system_prompt",
            sa.Text(),
            nullable=False,
            server_default=_DEFAULT_PROMPT,
        ),
    )


def downgrade() -> None:
    op.drop_column("guild_settings", "system_prompt")
