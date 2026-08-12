from __future__ import annotations

import asyncio

from peacemusic.adapters.discord.presenters.settings import settings_embed
from peacemusic.adapters.discord.views.settings import SetupView
from peacemusic.modules.settings.models import GuildSettings


def test_settings_presenter_renders_validated_section_values() -> None:
    embed = settings_embed(
        GuildSettings(guild_id=123),
        section="music",
    )

    assert embed.title == "⚙ PeaceMusic Settings — 🎵 Music"
    assert "Default Volume" in (embed.description or "")
    assert "70" in (embed.description or "")


class FakeSettingsService:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    async def update(self, guild_id: int, **kwargs: object) -> GuildSettings:
        self.updates.append({"guild_id": guild_id, **kwargs})
        return GuildSettings(guild_id=guild_id)


def test_setup_view_writes_through_settings_service() -> None:
    async def scenario() -> None:
        service = FakeSettingsService()
        view = SetupView(service, guild_id=123, actor_user_id=456)  # type: ignore[arg-type]

        class Response:
            async def edit_message(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            async def send_message(self, *args: object, **kwargs: object) -> None:
                raise AssertionError((args, kwargs))

        class FakeInteraction:
            response = Response()

        await view.on_channel_selected(FakeInteraction(), 789)  # type: ignore[arg-type]

        assert service.updates == [
            {
                "guild_id": 123,
                "actor_user_id": 456,
                "section": "general",
                "values": {"music_channel_id": 789},
            }
        ]

    asyncio.run(scenario())
