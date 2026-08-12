"""Setup wizard and settings navigation views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import discord
from pydantic import ValidationError as PydanticValidationError

from peacemusic.adapters.discord.presenters.settings import settings_embed
from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.music.roles import DJRoleRepository
from peacemusic.modules.settings.service import GuildSettingsService

_SECTIONS = ("general", "music", "voice", "ai", "memory")


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    """Metadata used to expose one validated guild setting in Discord."""

    key: str
    label: str
    description: str
    kind: str = "text"
    max_length: int = 100
    choices: tuple[str, ...] = ()


def _field(
    key: str,
    label: str,
    description: str,
    *,
    kind: str = "text",
    max_length: int = 100,
    choices: tuple[str, ...] = (),
) -> SettingDefinition:
    return SettingDefinition(
        key,
        label,
        description,
        kind=kind,
        max_length=max_length,
        choices=choices,
    )


_SETTING_DEFINITIONS: dict[str, tuple[SettingDefinition, ...]] = {
    "general": (
        _field(
            "language",
            "Language",
            "Language code used by the server settings.",
            max_length=16,
        ),
        _field(
            "music_channel_id",
            "Music channel",
            "Discord text-channel ID; leave blank to clear it.",
            kind="optional_int",
        ),
        _field(
            "notifications_enabled",
            "Notifications",
            "Enable bot status and playback notifications.",
            kind="bool",
        ),
    ),
    "music": (
        _field(
            "default_volume",
            "Default volume",
            "Volume applied when playback starts.",
            kind="int",
        ),
        _field(
            "max_volume",
            "Maximum volume",
            "Highest volume users may request.",
            kind="int",
        ),
        _field(
            "max_queue_size",
            "Maximum queue size",
            "Maximum number of queued tracks.",
            kind="int",
        ),
        _field(
            "autoplay_enabled",
            "Autoplay",
            "Request a recommendation when the queue ends.",
            kind="bool",
        ),
        _field(
            "default_loop_mode",
            "Default loop mode",
            "Initial repeat behavior: off, track, or queue.",
            kind="choice",
            choices=("off", "track", "queue"),
        ),
        _field(
            "track_announce",
            "Track announcements",
            "Announce newly started tracks.",
            kind="bool",
        ),
        _field(
            "allow_playlists",
            "Playlists",
            "Allow playlist URLs and playlist searches.",
            kind="bool",
        ),
        _field(
            "max_playlist_size",
            "Maximum playlist size",
            "Maximum tracks imported from one playlist.",
            kind="int",
        ),
        _field(
            "history_enabled",
            "Playback history",
            "Record tracks in the server playback history.",
            kind="bool",
        ),
        _field(
            "allow_direct_urls",
            "Direct URLs",
            "Allow users to play direct media URLs.",
            kind="bool",
        ),
        _field(
            "allow_search",
            "Search",
            "Allow provider-backed music searches.",
            kind="bool",
        ),
        _field(
            "audio_filters_enabled",
            "Audio filters",
            "Allow audio filter processing for playback.",
            kind="bool",
        ),
    ),
    "voice": (
        _field(
            "idle_disconnect_enabled",
            "Idle disconnect",
            "Disconnect after the player has been idle.",
            kind="bool",
        ),
        _field(
            "idle_disconnect_timeout",
            "Idle timeout",
            "Seconds before disconnecting an idle player.",
            kind="int",
        ),
        _field(
            "alone_pause_enabled",
            "Pause when alone",
            "Pause playback when no other member remains in voice.",
            kind="bool",
        ),
        _field(
            "alone_disconnect_timeout",
            "Alone timeout",
            "Seconds before disconnecting when alone.",
            kind="int",
        ),
        _field(
            "auto_resume_enabled",
            "Auto-resume",
            "Resume playback after a temporary voice interruption.",
            kind="bool",
        ),
        _field(
            "mode_24_7",
            "24/7 mode",
            "Keep the bot connected instead of applying normal idle rules.",
            kind="bool",
        ),
        _field(
            "default_voice_channel",
            "Default voice channel",
            "Discord voice-channel ID; leave blank to clear it.",
            kind="optional_int",
        ),
    ),
    "ai": (
        _field(
            "enabled",
            "AI enabled",
            "Allow the assistant to process messages in this server.",
            kind="bool",
        ),
        _field(
            "channel_id",
            "AI channel",
            "Discord text-channel ID; leave blank to allow configured routing.",
            kind="optional_int",
        ),
        _field(
            "require_mention",
            "Require mention",
            "Only respond when the bot is mentioned.",
            kind="bool",
        ),
        _field(
            "model",
            "AI model",
            "Model name from the operator allowlist.",
            max_length=100,
        ),
        _field(
            "system_prompt",
            "System prompt",
            "Per-server personality and behavior instructions.",
            kind="prompt",
            max_length=4000,
        ),
        _field(
            "temperature",
            "Temperature",
            "Controls response randomness; allowed range is 0 to 2.",
            kind="float",
        ),
        _field(
            "attachments_enabled",
            "Attachments",
            "Allow the assistant to inspect message attachments.",
            kind="bool",
        ),
        _field(
            "image_input_enabled",
            "Image input",
            "Allow image attachments as AI input.",
            kind="bool",
        ),
        _field(
            "video_input_enabled",
            "Video input",
            "Allow video attachments as AI input.",
            kind="bool",
        ),
        _field(
            "music_tools_enabled",
            "Music tools",
            "Allow the AI to call music and playback tools.",
            kind="bool",
        ),
        _field(
            "memory_tools_enabled",
            "Memory tools",
            "Allow the AI to read and write memory tools.",
            kind="bool",
        ),
        _field(
            "discord_tools_enabled",
            "Discord tools",
            "Allow the AI to use Discord information tools.",
            kind="bool",
        ),
        _field(
            "reactions_enabled",
            "Message reactions",
            "Add the bot reaction while processing an AI request.",
            kind="bool",
        ),
        _field(
            "per_user_rate_limit",
            "User rate limit",
            "Maximum AI requests per user in the rate window.",
            kind="int",
        ),
        _field(
            "turn_timeout",
            "Turn timeout",
            "Maximum seconds allowed for one AI turn.",
            kind="int",
        ),
    ),
    "memory": (
        _field(
            "enabled",
            "Memory enabled",
            "Enable memory features for this server.",
            kind="bool",
        ),
        _field(
            "short_term_memory_enabled",
            "Short-term memory",
            "Keep recent conversation context.",
            kind="bool",
        ),
        _field(
            "long_term_memory_enabled",
            "Long-term memory",
            "Persist durable conversation memories.",
            kind="bool",
        ),
        _field(
            "user_memory_enabled",
            "User memory",
            "Allow memories associated with individual users.",
            kind="bool",
        ),
        _field(
            "channel_memory_enabled",
            "Channel memory",
            "Allow memories scoped to channels.",
            kind="bool",
        ),
        _field(
            "semantic_search_enabled",
            "Semantic search",
            "Use vector similarity when retrieving memories.",
            kind="bool",
        ),
        _field(
            "summarization_enabled",
            "Summarization",
            "Summarize longer conversation context.",
            kind="bool",
        ),
        _field(
            "memory_retention_days",
            "Memory retention",
            "Days to retain stored memories; zero disables expiry.",
            kind="int",
        ),
    ),
}


def _definitions_for(section: str) -> tuple[SettingDefinition, ...]:
    return _SETTING_DEFINITIONS.get(section, ())


def _definition_for(section: str, key: str) -> SettingDefinition | None:
    return next((item for item in _definitions_for(section) if item.key == key), None)


def _display_value(value: Any) -> str:
    if value is None:
        return "not set"
    return str(value)


def _parse_value(definition: SettingDefinition, raw_value: str) -> Any:
    """Convert modal text into the type expected by GuildSettingsService."""

    value = raw_value.strip()
    if definition.kind == "prompt":
        return raw_value.strip()
    if definition.kind == "bool":
        normalized = value.casefold()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
        raise ValueError("enter true or false")
    if definition.kind == "int":
        return int(value)
    if definition.kind == "optional_int":
        return None if not value else int(value)
    if definition.kind == "float":
        return float(value)
    if definition.kind == "choice":
        if value not in definition.choices:
            raise ValueError(f"choose one of: {', '.join(definition.choices)}")
        return value
    if not value:
        raise ValueError("this value cannot be empty")
    return value


def _format_validation_error(exc: PydanticValidationError) -> str:
    messages = [str(error.get("msg", "invalid value")) for error in exc.errors()]
    return "; ".join(messages) or "invalid value"


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


class SettingsFieldSelect(discord.ui.Select["SectionSettingsView"]):
    def __init__(self, section: str, settings: Any) -> None:
        options = []
        for definition in _definitions_for(section):
            current = _display_value(getattr(settings, definition.key))
            description = f"{definition.description} Current: {current}"
            options.append(
                discord.SelectOption(
                    label=definition.label,
                    value=definition.key,
                    description=description[:100],
                )
            )
        super().__init__(
            placeholder="Select a setting to edit",
            options=options,
        )
        self.section = section

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is None:
            return
        definition = _definition_for(self.section, self.values[0])
        if definition is None:
            await interaction.response.send_message("Unknown setting.", ephemeral=True)
            return
        settings = await self.view.service.get(self.view.guild_id)
        current = getattr(getattr(settings, self.section), definition.key)
        await interaction.response.send_modal(
            SettingsFieldModal(
                self.view.service,
                section=self.section,
                definition=definition,
                guild_id=self.view.guild_id,
                actor_user_id=self.view.actor_user_id,
                current_value=current,
            )
        )


class SectionSettingsView(discord.ui.View):
    """Field editor for one section of the per-guild settings aggregate."""

    def __init__(
        self,
        service: GuildSettingsService,
        *,
        guild_id: int,
        actor_user_id: int,
        section: str,
        settings: Any,
    ) -> None:
        super().__init__(timeout=300)
        self.service = service
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self.section = section
        self._field_select = SettingsFieldSelect(section, getattr(settings, section))
        self.add_item(self._field_select)

    async def load_settings(self) -> Any:
        return await self.service.get(self.guild_id)

    async def refresh(self, interaction: discord.Interaction) -> None:
        settings = await self.load_settings()
        self.remove_item(self._field_select)
        self._field_select = SettingsFieldSelect(
            self.section, getattr(settings, self.section)
        )
        self.add_item(self._field_select)
        await interaction.response.edit_message(
            embed=settings_embed(settings, section=self.section),
            view=self,
        )

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary)
    async def refresh_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        try:
            await self.refresh(interaction)
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)

    @discord.ui.button(label="Back to sections", style=discord.ButtonStyle.primary)
    async def back_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        try:
            settings = await self.load_settings()
            await interaction.response.edit_message(
                embed=settings_embed(settings, section=self.section),
                view=SettingsView(
                    self.service,
                    guild_id=self.guild_id,
                    actor_user_id=self.actor_user_id,
                ),
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class SettingsFieldModal(discord.ui.Modal):
    """Edit one guild setting while preserving the model's validation rules."""

    value = discord.ui.TextInput(
        label="Value",
        style=discord.TextStyle.short,
        required=True,
    )

    def __init__(
        self,
        service: GuildSettingsService,
        *,
        section: str,
        definition: SettingDefinition,
        guild_id: int,
        actor_user_id: int,
        current_value: Any,
    ) -> None:
        title = f"Edit {definition.label}"[:45]
        super().__init__(title=title)
        self.service = service
        self.section = section
        self.definition = definition
        self.guild_id = guild_id
        self.actor_user_id = actor_user_id
        self.value.style = (
            discord.TextStyle.paragraph
            if definition.kind == "prompt"
            else discord.TextStyle.short
        )
        self.value.placeholder = definition.description[:100]
        self.value.default = "" if current_value is None else str(current_value)
        self.value.required = definition.kind != "optional_int"
        self.value.min_length = 1 if self.value.required else None
        self.value.max_length = definition.max_length

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            parsed = _parse_value(self.definition, str(self.value.value))
            settings = await self.service.update(
                self.guild_id,
                actor_user_id=self.actor_user_id,
                section=self.section,
                values={self.definition.key: parsed},
            )
            current = getattr(getattr(settings, self.section), self.definition.key)
            await interaction.response.send_message(
                f"✅ {self.definition.label} updated to `{_display_value(current)}`.",
                ephemeral=True,
            )
        except PydanticValidationError as exc:
            await interaction.response.send_message(
                f"Invalid value: {_format_validation_error(exc)}", ephemeral=True
            )
        except ValueError as exc:
            await interaction.response.send_message(
                f"Invalid value: {exc}", ephemeral=True
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


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
            view=SectionSettingsView(
                self.service,
                guild_id=self.guild_id,
                actor_user_id=self.actor_user_id,
                section=section,
                settings=settings,
            ),
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
