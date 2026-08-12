"""Create the application-owned PostgreSQL tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.BigInteger(), primary_key=True),
        sa.Column("language", sa.String(16), nullable=False, server_default="en"),
        sa.Column("music_channel_id", sa.BigInteger()),
        sa.Column("ai_channel_id", sa.BigInteger()),
        sa.Column("default_volume", sa.Integer(), nullable=False, server_default="70"),
        sa.Column("max_volume", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("max_queue_size", sa.Integer(), nullable=False, server_default="200"),
        sa.Column(
            "autoplay_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "track_announce", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "idle_disconnect_timeout",
            sa.Integer(),
            nullable=False,
            server_default="300",
        ),
        sa.Column("mode_24_7", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "require_ai_mention",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "ai_model",
            sa.String(128),
            nullable=False,
            server_default="gemini-3.1-flash-lite",
        ),
        sa.Column("ai_temperature", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "memory_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "guild_roles",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("role_name", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "role_id"),
    )
    op.create_table(
        "guild_permissions",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("guild_id", "subject_id", "capability"),
    )
    op.create_table(
        "disabled_users",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("guild_id", "user_id"),
    )
    op.create_table(
        "channel_mutes",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("silenced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "channel_id"),
    )
    op.create_table(
        "playlists",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("guild_id", "owner_user_id", "name"),
    )
    op.create_table(
        "playlist_tracks",
        sa.Column("playlist_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("duration", sa.Integer()),
        sa.PrimaryKeyConstraint("playlist_id", "position"),
    )
    op.create_table(
        "play_history",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "played_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("duration", sa.Integer()),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger()),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    for table in (
        "audit_events",
        "play_history",
        "playlist_tracks",
        "playlists",
        "channel_mutes",
        "disabled_users",
        "guild_permissions",
        "guild_roles",
        "guild_settings",
    ):
        op.drop_table(table)
