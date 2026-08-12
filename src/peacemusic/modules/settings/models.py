"""Validated guild configuration models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GeneralGuildSettings(BaseModel):
    language: str = Field(default="en", min_length=2, max_length=16)
    notifications_enabled: bool = True


class MusicGuildSettings(BaseModel):
    default_volume: int = Field(default=70, ge=0, le=100)
    max_volume: int = Field(default=100, ge=0, le=100)
    max_queue_size: int = Field(default=200, ge=1)
    autoplay_enabled: bool = False
    default_loop_mode: str = "off"
    track_announce: bool = True
    allow_playlists: bool = True
    max_playlist_size: int = Field(default=100, ge=1)
    history_enabled: bool = True
    allow_direct_urls: bool = True
    allow_search: bool = True
    audio_filters_enabled: bool = False

    @field_validator("default_loop_mode")
    @classmethod
    def validate_loop_mode(cls, value: str) -> str:
        if value not in {"off", "track", "queue"}:
            raise ValueError("default_loop_mode must be off, track, or queue")
        return value

    @model_validator(mode="after")
    def validate_volume_bounds(self) -> "MusicGuildSettings":
        if self.default_volume > self.max_volume:
            raise ValueError("default_volume cannot exceed max_volume")
        return self


class VoiceGuildSettings(BaseModel):
    idle_disconnect_enabled: bool = True
    idle_disconnect_timeout: int = Field(default=300, ge=0)
    alone_pause_enabled: bool = False
    alone_disconnect_timeout: int = Field(default=300, ge=0)
    auto_resume_enabled: bool = True
    mode_24_7: bool = False
    default_voice_channel: int | None = None


class AIGuildSettings(BaseModel):
    enabled: bool = True
    channel_id: int | None = None
    require_mention: bool = False
    model: str = "gemini-3.1-flash-lite"
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    attachments_enabled: bool = True
    image_input_enabled: bool = True
    video_input_enabled: bool = True
    music_tools_enabled: bool = True
    memory_tools_enabled: bool = True
    discord_tools_enabled: bool = True
    reactions_enabled: bool = True
    per_user_rate_limit: int = Field(default=20, ge=0)
    turn_timeout: int = Field(default=120, ge=1)


class MemoryGuildSettings(BaseModel):
    enabled: bool = True
    short_term_memory_enabled: bool = True
    long_term_memory_enabled: bool = True
    user_memory_enabled: bool = True
    channel_memory_enabled: bool = True
    semantic_search_enabled: bool = True
    summarization_enabled: bool = True
    memory_retention_days: int = Field(default=365, ge=0)


class GuildSettings(BaseModel):
    """Complete behavior configuration for one Discord guild."""

    model_config = ConfigDict(frozen=False)

    guild_id: int = Field(gt=0)
    general: GeneralGuildSettings = Field(default_factory=GeneralGuildSettings)
    music: MusicGuildSettings = Field(default_factory=MusicGuildSettings)
    voice: VoiceGuildSettings = Field(default_factory=VoiceGuildSettings)
    ai: AIGuildSettings = Field(default_factory=AIGuildSettings)
    memory: MemoryGuildSettings = Field(default_factory=MemoryGuildSettings)
