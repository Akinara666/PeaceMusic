"""Attachment preparation and provider-upload lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from peacemusic.modules.attachments.models import AttachmentInput, PreparedAttachment
from peacemusic.modules.attachments.service import AttachmentService
from peacemusic.infrastructure.llm.files import GeminiFileReference, GeminiFileService


class AttachmentProviderWorkflow:
    """Bridge Discord attachment metadata to the provider file lifecycle."""

    def __init__(self, attachment_service, file_service, *, downloader) -> None:
        self._attachment_service = attachment_service
        self._file_service = file_service
        self._downloader = downloader

    @asynccontextmanager
    async def prepare(self, attachments, *, retain_provider_files: bool = False):
        inputs = []
        for attachment in attachments:
            if not attachment.url:
                raise ValueError("Attachment URL is required for multimodal input")
            inputs.append(
                AttachmentInput(
                    attachment_id=attachment.attachment_id,
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                    size_bytes=attachment.size_bytes,
                    url=attachment.url,
                )
            )
        async with prepare_for_provider(
            self._attachment_service,
            self._file_service,
            inputs,
            downloader=self._downloader,
            retain_provider_files=retain_provider_files,
        ) as uploaded:
            yield uploaded


class PreparedProviderAttachment:
    def __init__(
        self, attachment: PreparedAttachment, provider_reference: GeminiFileReference
    ) -> None:
        self.attachment = attachment
        self.provider_reference = provider_reference


@asynccontextmanager
async def prepare_for_provider(
    attachment_service: AttachmentService,
    file_service: GeminiFileService,
    attachments: Sequence[AttachmentInput],
    *,
    downloader,
    retain_provider_files: bool = False,
) -> AsyncIterator[list[PreparedProviderAttachment]]:
    """Prepare files and retain provider references only after a successful turn."""

    uploaded: list[PreparedProviderAttachment] = []
    succeeded = False
    try:
        async with attachment_service.prepare(
            attachments, downloader=downloader
        ) as prepared:
            for attachment in prepared:
                reference = await file_service.upload(attachment)
                uploaded.append(PreparedProviderAttachment(attachment, reference))
            yield uploaded
            succeeded = True
    finally:
        if not retain_provider_files or not succeeded:
            for item in reversed(uploaded):
                await file_service.cleanup(item.provider_reference)
