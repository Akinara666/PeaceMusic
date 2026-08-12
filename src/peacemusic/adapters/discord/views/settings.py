"""Setup wizard and settings navigation views."""

from __future__ import annotations

import discord

from peacemusic.adapters.discord.presenters.settings import settings_embed
from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.music.roles import DJRoleRepository
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
    """Settings navigation whose mutations are delegated to the service."""

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
        self.section = "general"
        self.add_item(SettingsSectionSelect())

    @discord.ui.button(label="Toggle AI", style=discord.ButtonStyle.secondary)
    async def toggle_ai(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._toggle(interaction, "ai", "enabled")

    @discord.ui.button(label="Toggle autoplay", style=discord.ButtonStyle.secondary)
    async def toggle_autoplay(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._toggle(interaction, "music", "autoplay_enabled")

    @discord.ui.button(label="Toggle memory", style=discord.ButtonStyle.secondary)
    async def toggle_memory(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._toggle(interaction, "memory", "enabled")

    @discord.ui.button(label="Edit AI personality", style=discord.ButtonStyle.primary)
    async def edit_ai_personality(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        try:
            settings = await self.service.get(self.guild_id)
            await interaction.response.send_modal(
                AIPersonalityModal(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                    current_prompt=settings.ai.system_prompt,
                )
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)

    async def show_section(
        self, interaction: discord.Interaction, section: str
    ) -> None:
        if section not in _SECTIONS:
            return
        self.section = section
        settings = await self.service.get(self.guild_id)
        await interaction.response.edit_message(
            embed=settings_embed(settings, section=section),
            view=self,
        )

    async def _toggle(
        self, interaction: discord.Interaction, section: str, key: str
    ) -> None:
        try:
            settings = await self.service.get(self.guild_id)
            current = bool(getattr(getattr(settings, section), key))
            updated = await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section=section,
                values={key: not current},
            )
            self.section = section
            await interaction.response.edit_message(
                embed=settings_embed(updated, section=section),
                view=self,
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class AIPersonalityModal(discord.ui.Modal, title="AI personality"):
    """Edit the system prompt used for this guild's AI conversations."""

    prompt = discord.ui.TextInput(
        label="System prompt",
        style=discord.TextStyle.paragraph,
        placeholder="Describe the assistant's personality and behavior...",
        min_length=1,
        max_length=4000,
        required=True,
    )

    def __init__(
        self,
        service: GuildSettingsService,
        *,
        guild_id: int,
        actor_user_id: int,
        current_prompt: str,
    ) -> None:
        super().__init__()
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self.prompt.default = current_prompt

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section="ai",
                values={"system_prompt": str(self.prompt.value).strip()},
            )
            await interaction.response.send_message(
                "AI personality updated. The new personality will be used for the next AI request.",
                ephemeral=True,
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class SetupMusicChannelSelect(discord.ui.ChannelSelect):
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            await self.view.on_channel_selected(interaction, self.values[0])


class SetupAIChannelSelect(discord.ui.ChannelSelect):
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
        dj_roles: DJRoleRepository | None = None,
    ) -> None:
        super().__init__(timeout=600)
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self.dj_roles = dj_roles
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
                content="Step 2/7 — Select the AI channel:",
                embed=None,
                view=AIChannelSetupView(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                    dj_roles=self.dj_roles,
                ),
            )
        except (ValueError, PeaceMusicError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class AIChannelSetupView(discord.ui.View):
    def __init__(
        self,
        service: GuildSettingsService,
        *,
        guild_id: int,
        actor_user_id: int,
        dj_roles: DJRoleRepository | None,
    ) -> None:
        super().__init__(timeout=600)
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self.dj_roles = dj_roles
        self.add_item(
            SetupAIChannelSelect(
                placeholder="Select the AI channel",
                channel_types=[discord.ChannelType.text],
                min_values=1,
                max_values=1,
                custom_id="peacemusic_setup_ai_channel",
            )
        )

    async def on_channel_selected(
        self, interaction: discord.Interaction, channel: object
    ) -> None:
        try:
            await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section="ai",
                values={"channel_id": int(getattr(channel, "id", channel))},
            )
            await interaction.response.edit_message(
                content="Step 3/7 — Should the AI assistant be enabled?",
                view=AISetupView(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                    dj_roles=self.dj_roles,
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
        dj_roles: DJRoleRepository | None,
    ) -> None:
        super().__init__(timeout=600)
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self.dj_roles = dj_roles

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
            await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section="ai",
                values={"enabled": enabled},
            )
            await interaction.response.edit_message(
                content="Step 4/7 — Require a mention before the AI responds?",
                embed=None,
                view=SetupMentionView(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                    dj_roles=self.dj_roles,
                ),
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class SetupMentionView(discord.ui.View):
    def __init__(
        self,
        service: GuildSettingsService,
        *,
        guild_id: int,
        actor_user_id: int,
        dj_roles: DJRoleRepository | None,
    ) -> None:
        super().__init__(timeout=600)
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self.dj_roles = dj_roles

    @discord.ui.button(label="Require mention", style=discord.ButtonStyle.secondary)
    async def require_mention(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._finish(interaction, required=True)

    @discord.ui.button(label="Respond in AI channel", style=discord.ButtonStyle.success)
    async def allow_without_mention(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._finish(interaction, required=False)

    async def _finish(
        self, interaction: discord.Interaction, *, required: bool
    ) -> None:
        try:
            await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section="ai",
                values={"require_mention": required},
            )
            await interaction.response.edit_message(
                content="Step 5/7 — Select an optional DJ role:",
                embed=None,
                view=SetupDJRoleView(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                    dj_roles=self.dj_roles,
                ),
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class SetupDJRoleView(discord.ui.View):
    def __init__(
        self,
        service: GuildSettingsService,
        *,
        guild_id: int,
        actor_user_id: int,
        dj_roles: DJRoleRepository | None,
    ) -> None:
        super().__init__(timeout=600)
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self.dj_roles = dj_roles
        if dj_roles is not None:
            self.add_item(
                SetupRoleSelect(
                    placeholder="Select a DJ role",
                    min_values=1,
                    max_values=1,
                    custom_id="peacemusic_setup_dj_role",
                )
            )
        else:
            self.add_item(SetupSkipDJButton())

    async def on_role_selected(
        self, interaction: discord.Interaction, role: object
    ) -> None:
        try:
            if self.dj_roles is not None:
                await self.dj_roles.add_role(
                    self.guild_id,
                    int(getattr(role, "id")),
                    str(getattr(role, "name", "DJ")),
                )
            await interaction.response.edit_message(
                content="Step 6/7 — Choose the default volume:",
                view=SetupVolumeView(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                ),
            )
        except (ValueError, PeaceMusicError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class SetupRoleSelect(discord.ui.RoleSelect):
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            await self.view.on_role_selected(interaction, self.values[0])


class SetupSkipDJButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Skip DJ role", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            await self.view.on_role_selected(
                interaction, type("Role", (), {"id": 0, "name": "DJ"})()
            )


class SetupVolumeView(discord.ui.View):
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

    @discord.ui.button(label="50%", style=discord.ButtonStyle.secondary)
    async def volume_50(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._finish(interaction, 50)

    @discord.ui.button(label="70%", style=discord.ButtonStyle.success)
    async def volume_70(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._finish(interaction, 70)

    @discord.ui.button(label="100%", style=discord.ButtonStyle.secondary)
    async def volume_100(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._finish(interaction, 100)

    async def _finish(self, interaction: discord.Interaction, volume: int) -> None:
        try:
            await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section="music",
                values={"default_volume": volume},
            )
            await interaction.response.edit_message(
                content="Step 7/7 — Enable autoplay for this server?",
                embed=None,
                view=SetupAutoplayView(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                ),
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class SetupAutoplayView(discord.ui.View):
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

    @discord.ui.button(label="Enable autoplay", style=discord.ButtonStyle.success)
    async def enable_autoplay(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._finish(interaction, enabled=True)

    @discord.ui.button(label="Keep autoplay off", style=discord.ButtonStyle.secondary)
    async def disable_autoplay(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._finish(interaction, enabled=False)

    async def _finish(self, interaction: discord.Interaction, *, enabled: bool) -> None:
        try:
            settings = await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section="music",
                values={"autoplay_enabled": enabled},
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
