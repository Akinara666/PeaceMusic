"""PostgreSQL repository for the guild settings aggregate."""

from __future__ import annotations

from typing import Any

from peacemusic.infrastructure.persistence.database import PostgresDatabase
from peacemusic.modules.settings.models import (
    AIGuildSettings,
    GeneralGuildSettings,
    GuildSettings,
    MemoryGuildSettings,
    MusicGuildSettings,
    VoiceGuildSettings,
)


class PostgresGuildSettingsRepository:
    """Persist guild settings without exposing SQL to application services."""

    async def get(self, guild_id: int) -> GuildSettings | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT guild_id, language, music_channel_id, ai_channel_id,
                       default_volume, max_volume, max_queue_size,
                       autoplay_enabled, track_announce, idle_disconnect_timeout,
                       mode_24_7, ai_enabled, require_ai_mention, ai_model,
                       ai_temperature, memory_enabled
                  FROM guild_settings
                 WHERE guild_id = $1
                """,
                guild_id,
            )
        if row is None:
            return None
        return self._from_row(row)

    async def save(self, settings: GuildSettings) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO guild_settings (
                    guild_id, language, music_channel_id, ai_channel_id,
                    default_volume, max_volume, max_queue_size,
                    autoplay_enabled, track_announce, idle_disconnect_timeout,
                    mode_24_7, ai_enabled, require_ai_mention, ai_model,
                    ai_temperature, memory_enabled, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    $13, $14, $15, $16, CURRENT_TIMESTAMP
                )
                ON CONFLICT (guild_id) DO UPDATE SET
                    language = EXCLUDED.language,
                    music_channel_id = EXCLUDED.music_channel_id,
                    ai_channel_id = EXCLUDED.ai_channel_id,
                    default_volume = EXCLUDED.default_volume,
                    max_volume = EXCLUDED.max_volume,
                    max_queue_size = EXCLUDED.max_queue_size,
                    autoplay_enabled = EXCLUDED.autoplay_enabled,
                    track_announce = EXCLUDED.track_announce,
                    idle_disconnect_timeout = EXCLUDED.idle_disconnect_timeout,
                    mode_24_7 = EXCLUDED.mode_24_7,
                    ai_enabled = EXCLUDED.ai_enabled,
                    require_ai_mention = EXCLUDED.require_ai_mention,
                    ai_model = EXCLUDED.ai_model,
                    ai_temperature = EXCLUDED.ai_temperature,
                    memory_enabled = EXCLUDED.memory_enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                settings.guild_id,
                settings.general.language,
                settings.general.music_channel_id,
                settings.ai.channel_id,
                settings.music.default_volume,
                settings.music.max_volume,
                settings.music.max_queue_size,
                settings.music.autoplay_enabled,
                settings.music.track_announce,
                settings.voice.idle_disconnect_timeout,
                settings.voice.mode_24_7,
                settings.ai.enabled,
                settings.ai.require_mention,
                settings.ai.model,
                settings.ai.temperature,
                settings.memory.enabled,
            )

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    @staticmethod
    def _from_row(row: Any) -> GuildSettings:
        return GuildSettings(
            guild_id=row["guild_id"],
            general=GeneralGuildSettings(language=row["language"]),
            music=MusicGuildSettings(
                default_volume=row["default_volume"],
                max_volume=row["max_volume"],
                max_queue_size=row["max_queue_size"],
                autoplay_enabled=row["autoplay_enabled"],
                track_announce=row["track_announce"],
            ),
            voice=VoiceGuildSettings(
                idle_disconnect_timeout=row["idle_disconnect_timeout"],
                mode_24_7=row["mode_24_7"],
            ),
            ai=AIGuildSettings(
                enabled=row["ai_enabled"],
                channel_id=row["ai_channel_id"],
                require_mention=row["require_ai_mention"],
                model=row["ai_model"],
                temperature=row["ai_temperature"],
            ),
            memory=MemoryGuildSettings(enabled=row["memory_enabled"]),
        )
