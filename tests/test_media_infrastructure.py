from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import MediaExtractionError, PlaybackError, ValidationError
from peacemusic.infrastructure.media.buffered_source import BufferedAudioSource
from peacemusic.infrastructure.media.ytdlp import YtDlpMediaResolver
from peacemusic.modules.music.recovery import PlaybackRecoveryService


def test_ytdlp_resolver_enforces_trusted_url_domains() -> None:
    resolver = YtDlpMediaResolver(allowed_domains=("example.test",))

    assert resolver._normalize_target("https://example.test/video") == (
        "https://example.test/video"
    )
    assert resolver._normalize_target("ambient piano") == "ytsearch1:ambient piano"

    with pytest.raises(ValidationError, match="domain"):
        resolver._normalize_target("https://untrusted.test/video")


def test_ytdlp_metadata_is_translated_to_domain_model() -> None:
    media = YtDlpMediaResolver._to_media(
        {
            "title": "Example",
            "webpage_url": "https://example.test/video",
            "duration": 12.5,
            "uploader": "Artist",
            "url": "https://cdn.example.test/audio",
        }
    )

    assert media.title == "Example"
    assert media.duration == 12
    assert media.stream_url == "https://cdn.example.test/audio"

    with pytest.raises(MediaExtractionError, match="no source"):
        YtDlpMediaResolver._to_media({"title": "No URL"})


def test_buffered_audio_source_is_bounded_and_reports_underruns() -> None:
    buffer = BufferedAudioSource(capacity_frames=1, frame_size=4)
    assert buffer.read(timeout=0) == b"\x00" * 4
    assert buffer.stats().underruns == 1
    buffer.push(b"abcd")
    with pytest.raises(BufferError):
        buffer.push(b"efgh", timeout=0)
    assert buffer.read(timeout=0) == b"abcd"
    buffer.close()
    assert buffer.stats().closed is True


def test_recovery_is_bounded_and_refreshes_between_attempts() -> None:
    async def scenario() -> None:
        service = PlaybackRecoveryService(max_attempts=3, retry_delay_seconds=0)
        attempts: list[int] = []
        refreshes: list[bool] = []

        async def operation(attempt: int) -> str:
            attempts.append(attempt)
            if attempt < 3:
                raise RuntimeError("temporary")
            return "ok"

        async def refresh() -> None:
            refreshes.append(True)

        assert await service.run(operation, refresh_source=refresh) == "ok"
        assert attempts == [1, 2, 3]
        assert len(refreshes) == 2

        async def always_fails(attempt: int) -> str:
            raise RuntimeError("permanent")

        with pytest.raises(PlaybackError):
            await service.run(always_fails)

    asyncio.run(scenario())
