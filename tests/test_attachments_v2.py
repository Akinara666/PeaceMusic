from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import ValidationError
from peacemusic.modules.attachments.models import AttachmentInput
from peacemusic.modules.attachments.service import AttachmentService


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
