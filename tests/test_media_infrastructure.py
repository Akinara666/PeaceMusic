from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import MediaExtractionError, PlaybackError, ValidationError
from peacemusic.core.metrics import MetricsRegistry
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
    metrics = MetricsRegistry()
    buffer = BufferedAudioSource(capacity_frames=1, frame_size=4, metrics=metrics)
    assert buffer.read(timeout=0) == b"\x00" * 4
    assert buffer.stats().underruns == 1
    buffer.push(b"abcd")
    with pytest.raises(BufferError):
        buffer.push(b"efgh", timeout=0)
    assert buffer.read(timeout=0) == b"abcd"
    buffer.close()
    assert buffer.stats().closed is True
    rendered = metrics.render()
    assert "peacemusic_voice_buffer_underruns_total 1" in rendered
    assert "peacemusic_voice_buffered_frames" in rendered


def test_recovery_is_bounded_and_refreshes_between_attempts() -> None:
    async def scenario() -> None:
        metrics = MetricsRegistry()
        service = PlaybackRecoveryService(
            max_attempts=3, retry_delay_seconds=0, metrics=metrics
        )
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
        assert "peacemusic_voice_stream_restarts_total 4" in metrics.render()

    asyncio.run(scenario())


def test_ytdlp_resolver_records_request_error_and_duration_metrics(monkeypatch) -> None:
    async def scenario() -> None:
        metrics = MetricsRegistry()
        resolver = YtDlpMediaResolver(
            allowed_domains=("example.test",), metrics=metrics
        )

        def extract(_target: str) -> dict[str, object]:
            return {
                "title": "Example",
                "webpage_url": "https://example.test/video",
            }

        resolver._extract = extract  # type: ignore[method-assign]

        async def immediate_to_thread(function, *args):
            return function(*args)

        monkeypatch.setattr(
            "peacemusic.infrastructure.media.ytdlp.asyncio.to_thread",
            immediate_to_thread,
        )
        await resolver.resolve("https://example.test/video")

        rendered = metrics.render()
        assert "peacemusic_ytdlp_requests_total 1" in rendered
        assert "peacemusic_ytdlp_duration_seconds_count 1" in rendered

    asyncio.run(scenario())
