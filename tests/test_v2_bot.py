from __future__ import annotations

from types import SimpleNamespace

import discord

from peacemusic.adapters.discord.bot import PeaceMusicV2Bot


def test_v2_bot_uses_container_intents_and_service() -> None:
    container = SimpleNamespace(
        settings=SimpleNamespace(discord_intents=discord.Intents.none()),
        guild_settings=object(),
        music=SimpleNamespace(attach_runtime=lambda **kwargs: None),
    )

    bot = PeaceMusicV2Bot(container)  # type: ignore[arg-type]

    assert bot.container is container
    assert bot.is_ready_for_health is False
