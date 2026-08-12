"""Deterministic outer routing helpers around the agent subgraph."""

from __future__ import annotations

from enum import StrEnum

from peacemusic.modules.agent.state import AttachmentRef


class InputRoute(StrEnum):
    DIRECT_AUDIO = "direct_audio"
    AI_AGENT = "ai_agent"


def normalize_input(text: str) -> str:
    """Normalize user text without interpreting it as system instructions."""

    return " ".join(text.split())


def route_input(attachments: list[AttachmentRef]) -> InputRoute:
    """Route standalone audio attachments directly to music handling."""

    if any(
        attachment.content_type and attachment.content_type.lower().startswith("audio/")
        for attachment in attachments
    ):
        return InputRoute.DIRECT_AUDIO
    return InputRoute.AI_AGENT
