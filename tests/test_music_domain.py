from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import PermissionDeniedError, ValidationError
from peacemusic.infrastructure.persistence.repositories.in_memory_audit import (
    InMemoryAuditWriter,
)
from peacemusic.modules.audit.service import AuditService
from peacemusic.modules.music.models import LoopMode, ResolvedMedia, Track
from peacemusic.modules.music.permissions import MusicCapability, MusicRequestContext
from peacemusic.modules.music.player import GuildPlayer
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.queue import TrackQueue
from peacemusic.modules.music.service import MusicService


def track(number: int) -> Track:
    return Track(
        title=f"Track {number}",
        source_url=f"https://example.test/{number}",
        requested_by=1,
    )


def test_track_queue_orders_and_mutates_without_external_dependencies() -> None:
    queue = TrackQueue(max_size=3)
    queue.extend([track(1), track(2), track(3)])

    queue.move(2, 0)
    removed = queue.remove(1)

    assert removed.title == "Track 1"
    assert [item.title for item in queue.list()] == ["Track 3", "Track 2"]
    assert queue.advance() == track(3)
    assert queue.size == 1


def test_track_queue_enforces_capacity_and_loop_modes() -> None:
    queue = TrackQueue(max_size=2, tracks=[track(1)])
    queue.set_loop_mode(LoopMode.TRACK)
    assert queue.advance(track(1)) == track(1)

    queue.set_loop_mode(LoopMode.QUEUE)
    queue.add(track(2))
    assert queue.advance(track(1)) == track(1)
    assert queue.size == 2


def test_player_state_transitions_and_volume_limits() -> None:
    player = GuildPlayer(123, max_queue_size=2)
    player.enqueue(track(1))
    player.enqueue(track(2))

    assert player.current_track == track(1)
    assert player.is_active is True
    player.pause()
    player.resume()
    assert player.skip() == track(2)

    with pytest.raises(ValidationError):
        player.set_volume(101)
    player.set_volume(50)
    assert player.volume == 50


def test_player_seek_validates_and_updates_position() -> None:
    player = GuildPlayer(123)
    player.enqueue(
        Track(
            title="Timed",
            source_url="https://example.test/timed",
            requested_by=1,
            duration=120,
        )
    )

    assert player.seek(45) == 45
    assert player.position_seconds == 45
    with pytest.raises(ValidationError):
        player.seek(121)
    with pytest.raises(ValidationError):
        player.seek(-1)


class Resolver:
    async def resolve(self, query: str) -> ResolvedMedia:
        return ResolvedMedia(title=query, source_url=f"https://media.test/{query}")


class Permissions:
    def __init__(self, denied: MusicCapability | None = None) -> None:
        self.denied = denied

    async def allowed(
        self, context: MusicRequestContext, capability: MusicCapability
    ) -> bool:
        return capability is not self.denied


def test_music_service_is_shared_operation_boundary() -> None:
    async def scenario() -> None:
        manager = GuildPlayerManager(default_max_queue_size=5)
        service = MusicService(manager, Resolver(), Permissions())
        context = MusicRequestContext(guild_id=123, user_id=456)

        added = await service.play(context, "calm music")
        assert added.requested_by == 456
        assert (await service.player_state(123)).current_track == added

        await service.set_volume(context, 60)
        assert await service.seek(context, 30) == 30
        await service.set_loop_mode(context, LoopMode.QUEUE)
        assert (await service.player_state(123)).volume == 60
        assert (await service.player_state(123)).position_seconds == 30
        assert (await service.player_state(123)).queue.loop_mode is LoopMode.QUEUE

    asyncio.run(scenario())


def test_music_service_audits_side_effecting_operations() -> None:
    async def scenario() -> None:
        writer = InMemoryAuditWriter()
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            Permissions(),
            audit=AuditService(writer),
        )
        context = MusicRequestContext(guild_id=123, user_id=456)

        await service.play(context, "audited")
        await service.set_volume(context, 55)
        await service.stop(context)

        assert [event.event_type for event in writer.events] == [
            "PLAY",
            "SET_VOLUME",
            "STOP",
        ]

    asyncio.run(scenario())


def test_music_service_enforces_permission_before_resolving() -> None:
    async def scenario() -> None:
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            Permissions(MusicCapability.PLAY),
        )
        context = MusicRequestContext(guild_id=123, user_id=456)

        with pytest.raises(PermissionDeniedError):
            await service.play(context, "blocked")

    asyncio.run(scenario())


def test_music_service_can_resolve_search_results_without_enqueueing() -> None:
    async def scenario() -> None:
        manager = GuildPlayerManager()
        service = MusicService(manager, Resolver(), Permissions())
        context = MusicRequestContext(guild_id=123, user_id=456)

        result = await service.resolve_track(context, "search term")

        assert result.title == "search term"
        player = await service.player_state(123)
        assert player.current_track is None
        assert player.queue.list() == []

    asyncio.run(scenario())


def test_music_service_exposes_shared_queue_mutations() -> None:
    async def scenario() -> None:
        manager = GuildPlayerManager()
        service = MusicService(manager, Resolver(), Permissions())
        context = MusicRequestContext(guild_id=123, user_id=456)
        player = await manager.get_or_create(123)
        player.queue.extend([track(1), track(2), track(3)])

        removed = await service.remove_from_queue(context, 1)
        assert removed.title == "Track 2"
        await service.move_in_queue(context, 1, 0)
        await service.shuffle_queue(context)
        removed_count = await service.clear_queue(context)
        assert removed_count == 2

    asyncio.run(scenario())
