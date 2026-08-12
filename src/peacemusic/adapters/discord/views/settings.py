"""Setup wizard and settings navigation views."""

from __future__ import annotations

import discord

from peacemusic.adapters.discord.presenters.settings import settings_embed
from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.settings.service import GuildSettingsService

_SECTIONS = ("general", "music", "voice", "ai", "memory")


class SettingsSectionSelect(discord.ui.Select["SettingsView"]):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Select a settings section",
            options=[
                discord.SelectOption(label=section.title(), value=section)
                for section in _SECTIONS
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            await self.view.show_section(interaction, self.values[0])


class SettingsView(discord.ui.View):
    """Read-only navigation; all mutations belong to the service."""

    def __init__(
        self,
        service: GuildSettingsService,
        *,
        guild_id: int,
        actor_user_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self.add_item(SettingsSectionSelect())

    async def show_section(
        self, interaction: discord.Interaction, section: str
    ) -> None:
        settings = await self.service.get(self.guild_id)
        await interaction.response.edit_message(
            embed=settings_embed(settings, section=section),
            view=self,
        )


class SetupMusicChannelSelect(discord.ui.ChannelSelect):
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            await self.view.on_channel_selected(interaction, self.values[0])


class SetupView(discord.ui.View):
    """Small initial wizard that progressively writes through the service."""

    def __init__(
        self,
        service: GuildSettingsService,
        *,
        guild_id: int,
        actor_user_id: int,
    ) -> None:
        super().__init__(timeout=600)
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self._add_channel_step()

    def _add_channel_step(self) -> None:
        self.clear_items()
        self.add_item(
            SetupMusicChannelSelect(
                placeholder="Select the music command channel",
                channel_types=[discord.ChannelType.text],
                min_values=1,
                max_values=1,
                custom_id="peacemusic_setup_music_channel",
            )
        )

    async def on_channel_selected(
        self, interaction: discord.Interaction, channel: object
    ) -> None:
        try:
            channel_id = int(getattr(channel, "id", channel))
            await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section="general",
                values={"music_channel_id": channel_id},
            )
            await interaction.response.edit_message(
                content="Step 2/3 — Should the AI assistant be enabled?",
                embed=None,
                view=AISetupView(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                ),
            )
        except (ValueError, PeaceMusicError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class AISetupView(discord.ui.View):
    def __init__(
        self,
        service: GuildSettingsService,
        *,
        guild_id: int,
        actor_user_id: int,
    ) -> None:
        super().__init__(timeout=600)
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id

    @discord.ui.button(label="Enable AI", style=discord.ButtonStyle.success)
    async def enable_ai(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._finish(interaction, enabled=True)

    @discord.ui.button(label="Disable AI", style=discord.ButtonStyle.secondary)
    async def disable_ai(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._finish(interaction, enabled=False)

    async def _finish(self, interaction: discord.Interaction, *, enabled: bool) -> None:
        try:
            settings = await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section="ai",
                values={"enabled": enabled},
            )
            await interaction.response.edit_message(
                content="✅ PeaceMusic is configured. Use `/settings` to open the panel.",
                embed=settings_embed(settings),
                view=SettingsView(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                ),
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
