"""PostgreSQL repository for the complete guild settings aggregate."""

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
    """Persist all guild behavior settings without exposing SQL to services."""

    _COLUMNS = """
        guild_id, language, music_channel_id, notifications_enabled,
        ai_channel_id, default_volume, max_volume, max_queue_size,
        music_permission_mode, autoplay_enabled, default_loop_mode, track_announce,
        max_playlist_size,
        history_enabled, allow_direct_urls, allow_search, audio_filters_enabled,
        idle_disconnect_enabled, idle_disconnect_timeout, alone_pause_enabled,
        alone_disconnect_timeout, auto_resume_enabled, mode_24_7,
        default_voice_channel, ai_enabled, require_ai_mention, ai_model,
        ai_temperature, system_prompt, attachments_enabled, image_input_enabled,
        video_input_enabled, music_tools_enabled, memory_tools_enabled,
        discord_tools_enabled, reactions_enabled, per_user_rate_limit,
        turn_timeout, memory_enabled, short_term_memory_enabled,
        long_term_memory_enabled, user_memory_enabled, channel_memory_enabled,
        semantic_search_enabled, summarization_enabled, memory_retention_days
    """

    async def get(self, guild_id: int) -> GuildSettings | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {self._COLUMNS} FROM guild_settings WHERE guild_id = $1",
                guild_id,
            )
        return self._from_row(row) if row is not None else None

    async def save(self, settings: GuildSettings) -> None:
        values = self._values(settings)
        placeholders = ", ".join(f"${index}" for index in range(1, len(values) + 1))
        assignments = ", ".join(
            f"{column} = EXCLUDED.{column}" for column in self._column_names()[1:]
        )
        async with self._database.acquire() as connection:
            await connection.execute(
                f"""
                INSERT INTO guild_settings ({self._COLUMNS})
                VALUES ({placeholders})
                ON CONFLICT (guild_id) DO UPDATE SET
                    {assignments}, updated_at = CURRENT_TIMESTAMP
                """,
                *values,
            )

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    @staticmethod
    def _column_names() -> tuple[str, ...]:
        return (
            "guild_id",
            "language",
            "music_channel_id",
            "notifications_enabled",
            "ai_channel_id",
            "default_volume",
            "max_volume",
            "max_queue_size",
            "music_permission_mode",
            "autoplay_enabled",
            "default_loop_mode",
            "track_announce",
            "max_playlist_size",
            "history_enabled",
            "allow_direct_urls",
            "allow_search",
            "audio_filters_enabled",
            "idle_disconnect_enabled",
            "idle_disconnect_timeout",
            "alone_pause_enabled",
            "alone_disconnect_timeout",
            "auto_resume_enabled",
            "mode_24_7",
            "default_voice_channel",
            "ai_enabled",
            "require_ai_mention",
            "ai_model",
            "ai_temperature",
            "system_prompt",
            "attachments_enabled",
            "image_input_enabled",
            "video_input_enabled",
            "music_tools_enabled",
            "memory_tools_enabled",
            "discord_tools_enabled",
            "reactions_enabled",
            "per_user_rate_limit",
            "turn_timeout",
            "memory_enabled",
            "short_term_memory_enabled",
            "long_term_memory_enabled",
            "user_memory_enabled",
            "channel_memory_enabled",
            "semantic_search_enabled",
            "summarization_enabled",
            "memory_retention_days",
        )

    @staticmethod
    def _values(settings: GuildSettings) -> tuple[object, ...]:
        return (
            settings.guild_id,
            settings.general.language,
            settings.general.music_channel_id,
            settings.general.notifications_enabled,
            settings.ai.channel_id,
            settings.music.default_volume,
            settings.music.max_volume,
            settings.music.max_queue_size,
            settings.music.permission_mode,
            settings.music.autoplay_enabled,
            settings.music.default_loop_mode,
            settings.music.track_announce,
            settings.music.max_playlist_size,
            settings.music.history_enabled,
            settings.music.allow_direct_urls,
            settings.music.allow_search,
            settings.music.audio_filters_enabled,
            settings.voice.idle_disconnect_enabled,
            settings.voice.idle_disconnect_timeout,
            settings.voice.alone_pause_enabled,
            settings.voice.alone_disconnect_timeout,
            settings.voice.auto_resume_enabled,
            settings.voice.mode_24_7,
            settings.voice.default_voice_channel,
            settings.ai.enabled,
            settings.ai.require_mention,
            settings.ai.model,
            settings.ai.temperature,
            settings.ai.system_prompt,
            settings.ai.attachments_enabled,
            settings.ai.image_input_enabled,
            settings.ai.video_input_enabled,
            settings.ai.music_tools_enabled,
            settings.ai.memory_tools_enabled,
            settings.ai.discord_tools_enabled,
            settings.ai.reactions_enabled,
            settings.ai.per_user_rate_limit,
            settings.ai.turn_timeout,
            settings.memory.enabled,
            settings.memory.short_term_memory_enabled,
            settings.memory.long_term_memory_enabled,
            settings.memory.user_memory_enabled,
            settings.memory.channel_memory_enabled,
            settings.memory.semantic_search_enabled,
            settings.memory.summarization_enabled,
            settings.memory.memory_retention_days,
        )

    @staticmethod
    def _from_row(row: Any) -> GuildSettings:
        return GuildSettings(
            guild_id=row["guild_id"],
            general=GeneralGuildSettings(
                language=row["language"],
                music_channel_id=row["music_channel_id"],
                notifications_enabled=row["notifications_enabled"],
            ),
            music=MusicGuildSettings(
                default_volume=row["default_volume"],
                max_volume=row["max_volume"],
                max_queue_size=row["max_queue_size"],
                permission_mode=row["music_permission_mode"],
                autoplay_enabled=row["autoplay_enabled"],
                default_loop_mode=row["default_loop_mode"],
                track_announce=row["track_announce"],
                max_playlist_size=row["max_playlist_size"],
                history_enabled=row["history_enabled"],
                allow_direct_urls=row["allow_direct_urls"],
                allow_search=row["allow_search"],
                audio_filters_enabled=row["audio_filters_enabled"],
            ),
            voice=VoiceGuildSettings(
                idle_disconnect_enabled=row["idle_disconnect_enabled"],
                idle_disconnect_timeout=row["idle_disconnect_timeout"],
                alone_pause_enabled=row["alone_pause_enabled"],
                alone_disconnect_timeout=row["alone_disconnect_timeout"],
                auto_resume_enabled=row["auto_resume_enabled"],
                mode_24_7=row["mode_24_7"],
                default_voice_channel=row["default_voice_channel"],
            ),
            ai=AIGuildSettings(
                enabled=row["ai_enabled"],
                channel_id=row["ai_channel_id"],
                require_mention=row["require_ai_mention"],
                model=row["ai_model"],
                temperature=row["ai_temperature"],
                system_prompt=row["system_prompt"],
                attachments_enabled=row["attachments_enabled"],
                image_input_enabled=row["image_input_enabled"],
                video_input_enabled=row["video_input_enabled"],
                music_tools_enabled=row["music_tools_enabled"],
                memory_tools_enabled=row["memory_tools_enabled"],
                discord_tools_enabled=row["discord_tools_enabled"],
                reactions_enabled=row["reactions_enabled"],
                per_user_rate_limit=row["per_user_rate_limit"],
                turn_timeout=row["turn_timeout"],
            ),
            memory=MemoryGuildSettings(
                enabled=row["memory_enabled"],
                short_term_memory_enabled=row["short_term_memory_enabled"],
                long_term_memory_enabled=row["long_term_memory_enabled"],
                user_memory_enabled=row["user_memory_enabled"],
                channel_memory_enabled=row["channel_memory_enabled"],
                semantic_search_enabled=row["semantic_search_enabled"],
                summarization_enabled=row["summarization_enabled"],
                memory_retention_days=row["memory_retention_days"],
            ),
        )
