from __future__ import annotations

import asyncio
from types import SimpleNamespace

from peacemusic.adapters.discord.views.player import PlayerView
from peacemusic.modules.music.models import Track
from peacemusic.modules.music.permissions import AllowAllPermissionService
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.service import MusicService


class Resolver:
    async def resolve(self, query: str):
        raise AssertionError("player control should not resolve media")


class Response:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    def is_done(self) -> bool:
        return False

    async def edit_message(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def send_message(self, *args: object, **kwargs: object) -> None:
        raise AssertionError((args, kwargs))


def test_player_skip_button_calls_music_service_and_refreshes_message() -> None:
    async def scenario() -> None:
        manager = GuildPlayerManager()
        service = MusicService(manager, Resolver(), AllowAllPermissionService())
        player = await manager.get_or_create(123)
        player.enqueue(Track("First", "first", 1))
        player.enqueue(Track("Second", "second", 1))
        view = PlayerView(service)

        interaction = SimpleNamespace(
            guild=SimpleNamespace(id=123, voice_client=None),
            user=SimpleNamespace(
                id=456,
                voice=None,
                guild_permissions=SimpleNamespace(manage_guild=False),
            ),
            response=Response(),
        )
        skip_button = next(
            child
            for child in view.children
            if child.custom_id == "peacemusic_player_skip"
        )

        await skip_button.callback(interaction)

        assert player.current_track is not None
        assert player.current_track.title == "Second"
        assert interaction.response.kwargs is not None
        assert interaction.response.kwargs["view"] is view

    asyncio.run(scenario())
