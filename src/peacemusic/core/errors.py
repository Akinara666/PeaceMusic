"""Application-level errors shared by adapters and infrastructure."""

from __future__ import annotations


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
