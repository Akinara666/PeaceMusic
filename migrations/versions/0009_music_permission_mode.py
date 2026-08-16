"""Configure whether DJ-only music controls require a role."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_music_permission_mode"
down_revision = "0008_conversation_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_settings",
        sa.Column(
            "music_permission_mode",
            sa.String(length=16),
            nullable=False,
            server_default="role",
        ),
    )


def downgrade() -> None:
    op.drop_column("guild_settings", "music_permission_mode")
