"""Application lifecycle helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from peacemusic.bootstrap.container import ApplicationContainer, build_container
from peacemusic.core.config import AppSettings


@asynccontextmanager
async def application_lifespan(
    settings: AppSettings | None = None,
) -> AsyncIterator[ApplicationContainer]:
    """Start and reliably release all composition-root resources."""

    container = build_container(settings)
    await container.start()
    try:
        yield container
    finally:
        await container.stop()
