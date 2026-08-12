"""Untrusted attachment metadata and safe prepared-file references."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AttachmentInput:
    attachment_id: str
    filename: str
    content_type: str | None
    size_bytes: int
    url: str


@dataclass(frozen=True, slots=True)
class PreparedAttachment:
    attachment_id: str
    filename: str
    content_type: str
    path: Path
    size_bytes: int
