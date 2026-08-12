from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from peacemusic.core.errors import ValidationError
from peacemusic.modules.attachments.models import AttachmentInput
from peacemusic.modules.attachments.models import PreparedAttachment
from peacemusic.modules.attachments.service import AttachmentService
from peacemusic.infrastructure.llm.gemini_files import GeminiFilesAdapter


def attachment(**overrides) -> AttachmentInput:
    values = {
        "attachment_id": "a1",
        "filename": "photo.png",
        "content_type": "image/png",
        "size_bytes": 4,
        "url": "https://cdn.example.test/photo.png",
    }
    values.update(overrides)
    return AttachmentInput(**values)


def test_attachment_service_rejects_untrusted_metadata() -> None:
    service = AttachmentService(max_count=1, max_bytes=4)

    with pytest.raises(ValidationError, match="MIME"):
        service.validate([attachment(content_type="application/x-executable")])
    with pytest.raises(ValidationError, match="size"):
        service.validate([attachment(size_bytes=5)])
    with pytest.raises(ValidationError, match="Too many"):
        service.validate([attachment(), attachment(attachment_id="a2")])


def test_attachment_preparation_uses_safe_paths_and_cleans_up() -> None:
    async def scenario() -> None:
        service = AttachmentService(max_bytes=10)

        async def downloader(url: str) -> bytes:
            return b"data"

        async with service.prepare(
            [attachment(filename="../../secret.png")], downloader=downloader
        ) as prepared:
            path = prepared[0].path
            assert path.name.endswith(".png")
            assert "secret" not in path.name
            assert path.read_bytes() == b"data"
            directory = path.parent
        assert not directory.exists()

    asyncio.run(scenario())


def test_attachment_preparation_enforces_downloaded_size() -> None:
    async def scenario() -> None:
        service = AttachmentService(max_bytes=4)

        async def downloader(url: str) -> bytes:
            return b"too large"

        with pytest.raises(ValidationError, match="Downloaded"):
            async with service.prepare([attachment()], downloader=downloader):
                pass

    asyncio.run(scenario())


def test_gemini_files_adapter_uploads_and_cleans_provider_files(monkeypatch) -> None:
    from google import genai

    class Files:
        def upload(self, **_kwargs):
            return type("Uploaded", (), {"name": "files/1", "uri": "https://files/1"})()

        def delete(self, **kwargs):
            self.deleted = kwargs["name"]

    files = Files()
    monkeypatch.setattr(
        genai, "Client", lambda **_kwargs: type("Client", (), {"files": files})()
    )

    async def immediate_to_thread(function, *args):
        return function(*args)

    monkeypatch.setattr(
        "peacemusic.infrastructure.llm.gemini_files.asyncio.to_thread",
        immediate_to_thread,
    )

    async def scenario() -> None:
        adapter = GeminiFilesAdapter(api_key="secret")
        reference = await adapter.upload(
            PreparedAttachment("a", "photo.png", "image/png", Path("/tmp/photo.png"), 1)
        )
        assert reference.uri == "https://files/1"
        await adapter.cleanup(reference)
        assert files.deleted == "files/1"

    asyncio.run(scenario())
