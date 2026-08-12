from __future__ import annotations

from types import SimpleNamespace

import discord

from peacemusic.adapters.discord.bot import PeaceMusicV2Bot


class SettingsService:
    def __init__(self) -> None:
        self.authorizer = None

    def set_authorizer(self, authorizer: object) -> None:
        self.authorizer = authorizer


def test_bot_attaches_discord_authorizer_to_settings_service() -> None:
    settings = SettingsService()
    container = SimpleNamespace(
        settings=SimpleNamespace(discord_intents=discord.Intents.none()),
        guild_settings=settings,
        music=SimpleNamespace(attach_runtime=lambda **kwargs: None),
    )

    bot = PeaceMusicV2Bot(container)  # type: ignore[arg-type]

    assert settings.authorizer is not None
    assert settings.authorizer._bot is bot  # type: ignore[attr-defined]
