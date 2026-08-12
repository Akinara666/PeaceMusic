"""Presentation of guild settings without persistence concerns."""

from __future__ import annotations

import discord

from peacemusic.modules.settings.models import GuildSettings


def settings_embed(
    settings: GuildSettings, *, section: str = "general"
) -> discord.Embed:
    """Build a compact section view from a validated settings aggregate."""

    titles = {
        "general": "🌐 General",
        "music": "🎵 Music",
        "voice": "🔊 Voice",
        "ai": "🤖 AI",
        "memory": "🧠 Memory",
    }
    section_model = getattr(settings, section, settings.general)
    values = section_model.model_dump()
    description = "\n".join(
        f"**{key.replace('_', ' ').title()}:** `{value}`"
        for key, value in values.items()
    )
    return discord.Embed(
        title=f"⚙ PeaceMusic Settings — {titles.get(section, section)}",
        description=description or "No settings in this section.",
        color=discord.Color.blurple(),
    )
