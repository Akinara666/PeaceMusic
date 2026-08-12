from __future__ import annotations

import asyncio

from peacemusic.core.metrics import MetricsRegistry
from peacemusic.modules.music.models import ResolvedMedia
from peacemusic.modules.music.permissions import MusicRequestContext
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.service import MusicService


class Resolver:
    async def resolve(self, query: str) -> ResolvedMedia:
        return ResolvedMedia(title=query, source_url=f"https://media.test/{query}")


class AllowAllPermissions:
    async def allowed(self, context, capability) -> bool:
        return True


def test_music_service_increments_operation_metrics() -> None:
    async def scenario() -> None:
        metrics = MetricsRegistry()
        service = MusicService(
            GuildPlayerManager(default_max_queue_size=5),
            Resolver(),
            AllowAllPermissions(),
            metrics=metrics,
        )
        context = MusicRequestContext(guild_id=123, user_id=456)

        await service.play(context, "calm music")
        await service.set_volume(context, 60)

        rendered = metrics.render()
        assert "peacemusic_music_play_total 1" in rendered
        assert "peacemusic_music_volume_changes_total 1" in rendered

    asyncio.run(scenario())
