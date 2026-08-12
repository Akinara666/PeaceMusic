"""Persist the complete validated guild settings aggregate."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_complete_guild_settings"
down_revision = "0002_playlist_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        ("notifications_enabled", sa.Boolean(), sa.true()),
        ("default_loop_mode", sa.String(8), "off"),
        ("max_playlist_size", sa.Integer(), "100"),
        ("history_enabled", sa.Boolean(), sa.true()),
        ("allow_direct_urls", sa.Boolean(), sa.true()),
        ("allow_search", sa.Boolean(), sa.true()),
        ("audio_filters_enabled", sa.Boolean(), sa.false()),
        ("idle_disconnect_enabled", sa.Boolean(), sa.true()),
        ("alone_pause_enabled", sa.Boolean(), sa.false()),
        ("alone_disconnect_timeout", sa.Integer(), "300"),
        ("auto_resume_enabled", sa.Boolean(), sa.true()),
        ("default_voice_channel", sa.BigInteger(), None),
        ("attachments_enabled", sa.Boolean(), sa.true()),
        ("image_input_enabled", sa.Boolean(), sa.true()),
        ("video_input_enabled", sa.Boolean(), sa.true()),
        ("music_tools_enabled", sa.Boolean(), sa.true()),
        ("memory_tools_enabled", sa.Boolean(), sa.true()),
        ("discord_tools_enabled", sa.Boolean(), sa.true()),
        ("reactions_enabled", sa.Boolean(), sa.true()),
        ("per_user_rate_limit", sa.Integer(), "20"),
        ("turn_timeout", sa.Integer(), "120"),
        ("short_term_memory_enabled", sa.Boolean(), sa.true()),
        ("long_term_memory_enabled", sa.Boolean(), sa.true()),
        ("user_memory_enabled", sa.Boolean(), sa.true()),
        ("channel_memory_enabled", sa.Boolean(), sa.true()),
        ("semantic_search_enabled", sa.Boolean(), sa.true()),
        ("summarization_enabled", sa.Boolean(), sa.true()),
        ("memory_retention_days", sa.Integer(), "365"),
    )
    for name, column_type, default in columns:
        kwargs = {"nullable": False} if default is not None else {"nullable": True}
        if default is not None:
            kwargs["server_default"] = default
        op.add_column("guild_settings", sa.Column(name, column_type, **kwargs))


def downgrade() -> None:
    columns = (
        "memory_retention_days",
        "summarization_enabled",
        "semantic_search_enabled",
        "channel_memory_enabled",
        "user_memory_enabled",
        "long_term_memory_enabled",
        "short_term_memory_enabled",
        "turn_timeout",
        "per_user_rate_limit",
        "reactions_enabled",
        "discord_tools_enabled",
        "memory_tools_enabled",
        "music_tools_enabled",
        "video_input_enabled",
        "image_input_enabled",
        "attachments_enabled",
        "default_voice_channel",
        "auto_resume_enabled",
        "alone_disconnect_timeout",
        "alone_pause_enabled",
        "idle_disconnect_enabled",
        "audio_filters_enabled",
        "allow_search",
        "allow_direct_urls",
        "history_enabled",
        "max_playlist_size",
        "default_loop_mode",
        "notifications_enabled",
    )
    for name in columns:
        op.drop_column("guild_settings", name)
