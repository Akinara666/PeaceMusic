from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.stub_modules import install_stubs, load_project_module

install_stubs()
attachments_module = load_project_module(
    "test_attachments_module", "cogs/ai/attachments.py"
)

AttachmentProcessor = attachments_module.AttachmentProcessor
types = attachments_module.types


class AttachmentProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_to_content_for_generic_attachment_returns_text_only(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(files=SimpleNamespace()))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))
        message = SimpleNamespace(
            attachments=[SimpleNamespace(content_type="text/plain", url="https://file")],
            author=SimpleNamespace(name="alice"),
        )

        content, memory_text = await processor.to_content(
            message,
            "[2026-03-15 12:00:00] alice: note",
            "note",
        )

        self.assertEqual(memory_text, "note")
        self.assertEqual(content.role, "user")
        self.assertEqual(content.parts[0].text, "[2026-03-15 12:00:00] alice: note")

    async def test_to_content_for_image_uses_uploaded_file_and_fallback(self) -> None:
        files_api = SimpleNamespace(
            upload=AsyncMock(return_value=SimpleNamespace(name="uploaded")),
        )
        client = SimpleNamespace(aio=SimpleNamespace(files=files_api))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))
        processor._download_attachment = AsyncMock(return_value=Path("/tmp/uploaded.png"))
        processor._wait_for_file = AsyncMock(
            return_value=SimpleNamespace(uri="uri://image", mime_type="image/png")
        )
        message = SimpleNamespace(
            attachments=[SimpleNamespace(content_type="image/png", url="https://image")],
            author=SimpleNamespace(name="alice"),
        )

        content, memory_text = await processor.to_content(
            message,
            "[2026-03-15 12:00:00] alice",
            "",
        )

        self.assertEqual(memory_text, "[Image attachment]")
        self.assertEqual(content.parts[0].file_data.uri, "uri://image")
        self.assertEqual(content.parts[1].text, "[2026-03-15 12:00:00] alice [Image attachment]")
        files_api.upload.assert_awaited_once()

    async def test_download_attachment_writes_response_bytes(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(files=SimpleNamespace()))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))
        attachment = SimpleNamespace(url="https://example.com/file")

        class FakeResponse:
            content = b"payload"

            def raise_for_status(self):
                return None

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "download.bin"
            with patch.object(
                attachments_module.requests,
                "get",
                return_value=FakeResponse(),
            ) as get_mock:
                async def fake_to_thread(func, *args, **kwargs):
                    return func(*args, **kwargs)

                with patch.object(
                    attachments_module.asyncio,
                    "to_thread",
                    new=AsyncMock(side_effect=fake_to_thread),
                ):
                    result = await processor._download_attachment(attachment, target)
                    payload = result.read_bytes()

            self.assertEqual(result.name, "download.bin")
            self.assertEqual(payload, b"payload")
            get_mock.assert_called_once_with("https://example.com/file", timeout=30)

    async def test_wait_for_file_polls_until_active(self) -> None:
        files_api = SimpleNamespace(
            get=AsyncMock(
                side_effect=[
                    SimpleNamespace(state=SimpleNamespace(name="PROCESSING")),
                    SimpleNamespace(state=SimpleNamespace(name="ACTIVE")),
                ]
            )
        )
        client = SimpleNamespace(aio=SimpleNamespace(files=files_api))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))

        with patch.object(attachments_module.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            result = await processor._wait_for_file("file-1")

        self.assertEqual(result.state.name, "ACTIVE")
        sleep_mock.assert_awaited_once()

    async def test_wait_for_file_raises_for_terminal_state(self) -> None:
        files_api = SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(state=SimpleNamespace(name="FAILED"))
            )
        )
        client = SimpleNamespace(aio=SimpleNamespace(files=files_api))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))

        with self.assertRaises(RuntimeError):
            await processor._wait_for_file("file-2")
