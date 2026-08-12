from __future__ import annotations

import asyncio
from types import SimpleNamespace

from peacemusic.adapters.discord.views.player import PlayerView
from peacemusic.adapters.discord.cogs.music import MusicCog
from peacemusic.infrastructure.persistence.repositories.in_memory_player_messages import (
    InMemoryPlayerMessageRepository,
)
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


def test_player_buttons_share_pause_stop_and_shuffle_operations() -> None:
    async def scenario() -> None:
        manager = GuildPlayerManager()
        service = MusicService(manager, Resolver(), AllowAllPermissionService())
        player = await manager.get_or_create(123)
        player.enqueue(Track("First", "first", 1))
        player.enqueue(Track("Second", "second", 1))
        view = PlayerView(service)

        def make_interaction():
            return SimpleNamespace(
                guild=SimpleNamespace(id=123, voice_client=None),
                user=SimpleNamespace(
                    id=456,
                    voice=None,
                    roles=(),
                    guild_permissions=SimpleNamespace(manage_guild=False),
                ),
                response=Response(),
            )

        for custom_id in (
            "peacemusic_player_pause",
            "peacemusic_player_shuffle",
            "peacemusic_player_stop",
        ):
            button = next(
                child for child in view.children if child.custom_id == custom_id
            )
            await button.callback(make_interaction())

        assert player.status.value == "stopped"

    asyncio.run(scenario())


def test_music_command_reuses_persisted_player_message() -> None:
    class MusicServiceStub:
        async def play(self, _context, _query):
            return Track("Queued", "https://example.test", 456)

    class Response:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def is_done(self) -> bool:
            return False

        async def send_message(self, *args: object, **kwargs: object) -> None:
            self.calls.append({"args": args, **kwargs})

    class Message:
        id = 999

        async def edit(self, **kwargs: object) -> None:
            self.edited = kwargs

    async def scenario() -> None:
        repository = InMemoryPlayerMessageRepository()
        await repository.save(123, channel_id=321, message_id=999)
        message = Message()

        async def fetch_message(_message_id: int):
            return message

        interaction = SimpleNamespace(
            guild=SimpleNamespace(id=123, voice_client=None),
            channel=SimpleNamespace(id=321, fetch_message=fetch_message),
            user=SimpleNamespace(
                id=456,
                voice=None,
                roles=(),
                guild_permissions=SimpleNamespace(manage_guild=False),
            ),
            response=Response(),
        )
        cog = MusicCog(MusicServiceStub(), player_messages=repository)  # type: ignore[arg-type]

        await cog.play.callback(cog, interaction, "query")

        assert message.edited["embed"].title == "Queued"
        assert interaction.response.calls[0]["ephemeral"] is True

    asyncio.run(scenario())
