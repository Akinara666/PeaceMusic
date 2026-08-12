from __future__ import annotations

import asyncio

import httpx
import pytest

from peacemusic.core.errors import ExternalServiceError
from peacemusic.infrastructure.attachments.downloader import HttpAttachmentDownloader


def test_attachment_downloader_returns_bytes_and_translates_http_errors(
    monkeypatch,
) -> None:
    class Response:
        content = b"data"

        def raise_for_status(self) -> None:
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url):
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: Client())

    async def scenario() -> None:
        assert await HttpAttachmentDownloader()("https://example.test/file") == b"data"

        class FailingClient(Client):
            async def get(self, _url):
                raise httpx.ConnectError("offline")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FailingClient())
        with pytest.raises(ExternalServiceError):
            await HttpAttachmentDownloader()("https://example.test/file")

    asyncio.run(scenario())
