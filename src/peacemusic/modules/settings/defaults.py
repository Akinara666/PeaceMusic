"""System defaults for newly seen guilds."""

from __future__ import annotations

from peacemusic.core.config import DEFAULT_AGENT_SYSTEM_PROMPT, GlobalLimits
from peacemusic.modules.settings.models import AIGuildSettings, GuildSettings


def default_guild_settings(
    guild_id: int,
    *,
    limits: GlobalLimits | None = None,
    allowed_models: tuple[str, ...] = ("gemini-3.1-flash-lite",),
    default_system_prompt: str = DEFAULT_AGENT_SYSTEM_PROMPT,
) -> GuildSettings:
    """Return safe defaults clamped to operator-owned limits."""

    resolved_limits = limits or GlobalLimits()
    model = allowed_models[0]
    return GuildSettings(
        guild_id=guild_id,
        music={"max_queue_size": resolved_limits.max_queue_size},
        ai=AIGuildSettings(model=model, system_prompt=default_system_prompt),
    )
