from __future__ import annotations

import asyncio
from pathlib import Path

from peacemusic.modules.agent.state import AttachmentRef
from peacemusic.modules.attachments.service import AttachmentService
from peacemusic.modules.attachments.workflow import AttachmentProviderWorkflow
from peacemusic.infrastructure.llm.files import GeminiFileReference


class Files:
    def __init__(self) -> None:
        self.cleaned: list[str] = []

    async def upload(self, attachment):
        assert attachment.path.exists()
        return GeminiFileReference(
            "files/1", "https://files.test/1", attachment.content_type
        )

    async def cleanup(self, reference):
        self.cleaned.append(reference.name)


def test_attachment_workflow_cleans_local_and_provider_files() -> None:
    async def scenario() -> None:
        files = Files()
        workflow = AttachmentProviderWorkflow(
            AttachmentService(max_bytes=10),
            files,
            downloader=lambda _url: asyncio.sleep(0, result=b"data"),
        )
        attachment = AttachmentRef(
            attachment_id="1",
            filename="image.png",
            content_type="image/png",
            size_bytes=4,
            url="https://discord.test/image.png",
        )

        async with workflow.prepare([attachment]) as prepared:
            assert prepared[0].provider_reference.uri == "https://files.test/1"
            assert prepared[0].attachment.path.exists()
            path: Path = prepared[0].attachment.path
        assert not path.exists()
        assert files.cleaned == ["files/1"]

    asyncio.run(scenario())


def test_attachment_workflow_retains_provider_files_after_success() -> None:
    async def scenario() -> None:
        files = Files()
        workflow = AttachmentProviderWorkflow(
            AttachmentService(max_bytes=10),
            files,
            downloader=lambda _url: asyncio.sleep(0, result=b"data"),
        )
        attachment = AttachmentRef(
            attachment_id="1",
            filename="image.png",
            content_type="image/png",
            size_bytes=4,
            url="https://discord.test/image.png",
        )

        async with workflow.prepare(
            [attachment], retain_provider_files=True
        ) as prepared:
            assert prepared[0].provider_reference.uri == "https://files.test/1"

        assert files.cleaned == []

    asyncio.run(scenario())
