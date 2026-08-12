from __future__ import annotations

import asyncio

from peacemusic.adapters.discord.views.settings import SettingsView, SetupAutoplayView
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
