"""yt-dlp-backed autoplay candidate provider."""

from __future__ import annotations

from peacemusic.modules.autoplay.models import AutoplayContext, TrackCandidate
from peacemusic.modules.music.ports import MediaResolver


class ResolverAutoplayProvider:
    """Use the existing bounded resolver for a related-track search."""

    def __init__(self, resolver: MediaResolver) -> None:
        self._resolver = resolver

    async def get_next(self, context: AutoplayContext) -> TrackCandidate | None:
        previous = context.previous_track
        query = " ".join(
            part for part in (previous.title, previous.uploader or "") if part
        )
        media = await self._resolver.resolve(query)
        if media.source_url == previous.source_url:
            return None
        return TrackCandidate(
            title=media.title,
            source_url=media.source_url,
            duration=media.duration,
        )
