from __future__ import annotations

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


class AttachmentProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_to_content_for_generic_attachment_keeps_marker_in_prompt(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(files=SimpleNamespace()))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))
        message = SimpleNamespace(
            attachments=[
                SimpleNamespace(
                    content_type="text/plain",
                    filename="notes.txt",
                    url="https://file",
                )
            ],
            author=SimpleNamespace(name="alice"),
        )

        content, memory_text = await processor.to_content(
            message,
            "[2026-03-15 12:00:00] alice: note",
            "note",
        )

        self.assertEqual(memory_text, "note\n[Attachment: notes.txt]")
        self.assertEqual(content.role, "user")
        self.assertEqual(
            content.parts[0].text,
            "[2026-03-15 12:00:00] alice: note [Attachment: notes.txt]",
        )

    async def test_to_content_for_image_uses_uploaded_file_and_fallback(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(files=SimpleNamespace()))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))
        processor._upload_attachment = AsyncMock(
            return_value=SimpleNamespace(uri="uri://image", mime_type="image/png")
        )
        message = SimpleNamespace(
            attachments=[
                SimpleNamespace(
                    content_type="image/png",
                    filename="cat.png",
                    url="https://image",
                )
            ],
            author=SimpleNamespace(name="alice"),
        )

        content, memory_text = await processor.to_content(
            message,
            "[2026-03-15 12:00:00] alice",
            "",
        )

        self.assertEqual(memory_text, "[Image attachment: cat.png]")
        self.assertEqual(content.parts[0].file_data.uri, "uri://image")
        self.assertEqual(
            content.parts[1].text,
            "[2026-03-15 12:00:00] alice [Image attachment: cat.png]",
        )

    async def test_to_content_infers_media_type_from_filename(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(files=SimpleNamespace()))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))
        processor._upload_attachment = AsyncMock(
            return_value=SimpleNamespace(uri="uri://photo", mime_type="image/jpeg")
        )
        message = SimpleNamespace(
            attachments=[
                SimpleNamespace(
                    content_type=None,
                    filename="photo.jpg",
                    url="https://image",
                )
            ],
            author=SimpleNamespace(name="alice"),
        )

        content, memory_text = await processor.to_content(
            message,
            "[2026-03-15 12:00:00] alice",
            "",
        )

        self.assertEqual(memory_text, "[Image attachment: photo.jpg]")
        self.assertEqual(content.parts[0].file_data.mime_type, "image/jpeg")
        processor._upload_attachment.assert_awaited_once_with(
            message.attachments[0], "image/jpeg"
        )

    async def test_to_content_handles_multiple_attachments(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(files=SimpleNamespace()))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))
        processor._upload_attachment = AsyncMock(
            return_value=SimpleNamespace(uri="uri://image", mime_type="image/png")
        )
        message = SimpleNamespace(
            attachments=[
                SimpleNamespace(
                    content_type="image/png",
                    filename="cat.png",
                    url="https://image",
                ),
                SimpleNamespace(
                    content_type="text/plain",
                    filename="notes.txt",
                    url="https://file",
                ),
            ],
            author=SimpleNamespace(name="alice"),
        )

        content, memory_text = await processor.to_content(
            message,
            "[2026-03-15 12:00:00] alice: look",
            "look",
        )

        self.assertEqual(content.parts[0].file_data.uri, "uri://image")
        self.assertEqual(
            content.parts[1].text,
            "[2026-03-15 12:00:00] alice: look [Attachment: notes.txt]",
        )
        self.assertEqual(
            memory_text,
            "look\n[Image attachment: cat.png]\n[Attachment: notes.txt]",
        )

    async def test_to_content_falls_back_to_text_when_upload_fails(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(files=SimpleNamespace()))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))
        processor._upload_attachment = AsyncMock(side_effect=RuntimeError("upload failed"))
        message = SimpleNamespace(
            attachments=[
                SimpleNamespace(
                    content_type="image/png",
                    filename="cat.png",
                    url="https://image",
                )
            ],
            author=SimpleNamespace(name="alice"),
        )

        content, memory_text = await processor.to_content(
            message,
            "[2026-03-15 12:00:00] alice",
            "",
        )

        self.assertEqual(memory_text, "[Image attachment: cat.png]")
        self.assertEqual(len(content.parts), 1)
        self.assertEqual(
            content.parts[0].text,
            "[2026-03-15 12:00:00] alice [Image attachment: cat.png]",
        )

    async def test_download_attachment_writes_response_bytes(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(files=SimpleNamespace()))
        processor = AttachmentProcessor(client, Path("image.png"), Path("video.mp4"))
        attachment = SimpleNamespace(
            filename="photo.png",
            read=AsyncMock(return_value=b"payload"),
        )

        with patch.object(
            attachments_module.asyncio,
            "to_thread",
            new=AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)),
        ):
            result = await processor._download_attachment(attachment, "image/png")
            payload = result.read_bytes()

        try:
            self.assertEqual(result.suffix, ".png")
            self.assertEqual(payload, b"payload")
            attachment.read.assert_awaited_once_with(use_cached=True)
        finally:
            result.unlink(missing_ok=True)

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
