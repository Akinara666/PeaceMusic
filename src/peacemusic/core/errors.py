"""Application-level errors shared by adapters and infrastructure."""

from __future__ import annotations

import re

_SENSITIVE_VALUE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|token|password|secret)=([^\s&]+)"
)


class PeaceMusicError(Exception):
    """Base class for expected errors that can be presented to a user."""


class ValidationError(PeaceMusicError):
    """An input or configuration value failed validation."""


class PermissionDeniedError(PeaceMusicError):
    """The caller is not allowed to perform an operation."""


class ResourceNotFoundError(PeaceMusicError):
    """A requested application resource does not exist."""


class ExternalServiceError(PeaceMusicError):
    """An external dependency failed in a way visible to the application."""


class LLMError(ExternalServiceError):
    """The configured language-model provider failed."""


class MediaExtractionError(ExternalServiceError):
    """A media resolver could not obtain a playable source."""


class PlaybackError(PeaceMusicError):
    """A player could not start or maintain playback."""


def describe_exception(error: BaseException, *, max_length: int = 1200) -> str:
    """Return a concise, model-safe description of an exception chain.

    Infrastructure adapters commonly translate a provider exception into a
    domain exception with ``raise ... from exc``.  ``str(error)`` alone loses
    the provider's useful diagnostic, so include the complete cause chain while
    removing common credential-like query parameters and bounding its size.
    """

    messages: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).strip()
        if message and message not in messages:
            messages.append(message)
        current = current.__cause__ or current.__context__

    if not messages:
        messages.append(type(error).__name__)
    description = ": ".join(messages)
    description = _SENSITIVE_VALUE.sub(r"\1=[redacted]", description)
    if len(description) > max_length:
        return description[: max_length - 1].rstrip() + "…"
    return description
