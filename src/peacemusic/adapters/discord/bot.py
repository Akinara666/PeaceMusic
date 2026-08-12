"""Discord composition adapter for the incrementally built v2 application."""

from __future__ import annotations

import discord
from discord.ext import commands

from peacemusic.adapters.discord.cogs.settings import SettingsCog
from peacemusic.bootstrap.container import ApplicationContainer


class PeaceMusicV2Bot(commands.Bot):
    """Own Discord adapters while application services stay in the container."""

    def __init__(self, container: ApplicationContainer) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=container.settings.discord_intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.container = container
        self._ready = False

    @property
    def is_ready_for_health(self) -> bool:
        return self._ready

    async def setup_hook(self) -> None:
        await self.add_cog(SettingsCog(self.container.guild_settings))
        await self.tree.sync()

    async def on_ready(self) -> None:
        self._ready = True
        self.container.mark_discord_ready(True)

    async def on_disconnect(self) -> None:
        self._ready = False
        self.container.mark_discord_ready(False)
