"""Recommendation provider port for autoplay."""

from __future__ import annotations

from typing import Protocol

from peacemusic.modules.autoplay.models import AutoplayContext, TrackCandidate


class AutoplayProvider(Protocol):
    async def get_next(self, context: AutoplayContext) -> TrackCandidate | None:
        """Return one candidate, or no candidate when recommendations are exhausted."""
