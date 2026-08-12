from __future__ import annotations

import asyncio

from peacemusic.adapters.discord.views.settings import (
    AIPersonalityModal,
    SectionSettingsView,
    SettingsFieldSelect,
    SettingsView,
    SetupAutoplayView,
    _SETTING_DEFINITIONS,
    _definition_for,
    _parse_value,
)
from peacemusic.modules.settings.models import GuildSettings


class FakeSettingsService:
    def __init__(self) -> None:
        self.settings = GuildSettings(guild_id=123)
        self.updates: list[dict[str, object]] = []

    async def get(self, guild_id: int) -> GuildSettings:
        return self.settings

    async def update(self, guild_id: int, **kwargs: object) -> GuildSettings:
        self.updates.append({"guild_id": guild_id, **kwargs})
        section = kwargs["section"]
        values = kwargs["values"]
        self.settings = GuildSettings.model_validate(
            self.settings.model_copy(
                update={
                    section: getattr(self.settings, section).model_copy(update=values)
                }
            ).model_dump()
        )
        return self.settings


class Response:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    async def edit_message(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def send_message(self, *args: object, **kwargs: object) -> None:
        raise AssertionError((args, kwargs))


def test_settings_toggle_writes_through_service() -> None:
    async def scenario() -> None:
        service = FakeSettingsService()
        view = SettingsView(service, guild_id=123, actor_user_id=456)  # type: ignore[arg-type]
        interaction = type("Interaction", (), {"response": Response()})()

        await view._toggle(interaction, "music", "autoplay_enabled")  # type: ignore[arg-type]

        assert service.settings.music.autoplay_enabled is True
        assert service.updates == [
            {
                "guild_id": 123,
                "actor_user_id": 456,
                "section": "music",
                "values": {"autoplay_enabled": True},
            }
        ]

    asyncio.run(scenario())


def test_setup_autoplay_step_writes_through_service() -> None:
    async def scenario() -> None:
        service = FakeSettingsService()
        view = SetupAutoplayView(service, guild_id=123, actor_user_id=456)
        interaction = type("Interaction", (), {"response": Response()})()

        await view._finish(interaction, enabled=True)

        assert service.settings.music.autoplay_enabled is True
        assert interaction.response.kwargs is not None
        assert "configured" in str(interaction.response.kwargs["content"])

    asyncio.run(scenario())


def test_ai_personality_modal_prefills_current_guild_prompt() -> None:
    service = FakeSettingsService()
    modal = AIPersonalityModal(
        service,  # type: ignore[arg-type]
        guild_id=123,
        actor_user_id=456,
        current_prompt="Be calm and concise.",
    )

    assert modal.prompt.default == "Be calm and concise."


def test_settings_editor_exposes_every_guild_setting() -> None:
    settings = GuildSettings(guild_id=123)

    for section, definitions in _SETTING_DEFINITIONS.items():
        assert {item.key for item in definitions} == set(
            getattr(settings, section).model_dump()
        )
        view = SectionSettingsView(
            FakeSettingsService(),
            guild_id=123,
            actor_user_id=456,
            section=section,
            settings=settings,
        )  # type: ignore[arg-type]
        selector = next(
            item for item in view.children if isinstance(item, SettingsFieldSelect)
        )
        assert len(selector.options) == len(definitions)


def test_settings_editor_parses_supported_value_types() -> None:
    assert _parse_value(_definition_for("ai", "enabled"), "off") is False  # type: ignore[arg-type]
    assert _parse_value(_definition_for("music", "default_volume"), "80") == 80  # type: ignore[arg-type]
    assert _parse_value(_definition_for("ai", "temperature"), "0.25") == 0.25  # type: ignore[arg-type]
    assert _parse_value(_definition_for("voice", "default_voice_channel"), "") is None  # type: ignore[arg-type]
    assert _parse_value(_definition_for("music", "default_loop_mode"), "queue") == "queue"  # type: ignore[arg-type]


def test_settings_editor_refresh_keeps_navigation_buttons() -> None:
    async def scenario() -> None:
        service = FakeSettingsService()
        view = SectionSettingsView(
            service,
            guild_id=123,
            actor_user_id=456,
            section="music",
            settings=service.settings,
        )  # type: ignore[arg-type]
        interaction = type("Interaction", (), {"response": Response()})()

        await view.refresh(interaction)

        assert {getattr(item, "label", None) for item in view.children} >= {
            "Refresh",
            "Back to sections",
        }

    asyncio.run(scenario())
