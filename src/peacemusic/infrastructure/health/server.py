"""Small internal HTTP server for liveness, readiness, and metrics."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

ReadinessCheck = Callable[[], bool | Awaitable[bool]]
MetricsProvider = Callable[[], str]


class HealthServer:
    """Expose operational endpoints without coupling them to Discord."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        readiness_check: ReadinessCheck,
        metrics_provider: MetricsProvider | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._readiness_check = readiness_check
        self._metrics_provider = metrics_provider or (lambda: "")
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def set_readiness_check(self, readiness_check: ReadinessCheck) -> None:
        """Replace the readiness probe after dependent resources are composed."""

        self._readiness_check = readiness_check

    async def start(self) -> None:
        if self._runner is not None:
            return
        app = web.Application()
        app.router.add_get("/health/live", self._live)
        app.router.add_get("/health/ready", self._ready)
        app.router.add_get("/metrics", self._metrics)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        self._site = None
        self._runner = None

    async def _live(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _ready(self, _request: web.Request) -> web.Response:
        result: Any = self._readiness_check()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return web.json_response({"status": "ready"})
        return web.json_response({"status": "not_ready"}, status=503)

    async def _metrics(self, _request: web.Request) -> web.Response:
        return web.Response(
            text=self._metrics_provider(),
            content_type="text/plain",
        )
