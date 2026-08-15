from __future__ import annotations

import asyncio
import sys
import types

import discord
import pytest

from peacemusic.core.errors import (
    MediaExtractionError,
    PlaybackError,
    ValidationError,
    describe_exception,
)
from peacemusic.core.metrics import MetricsRegistry
from peacemusic.infrastructure.media.buffered_source import BufferedAudioSource
from peacemusic.infrastructure.media.ffmpeg import (
    FFmpegAudioSourceFactory,
    cleanup_audio_source,
)
from peacemusic.infrastructure.media.ytdlp import YtDlpMediaResolver
from peacemusic.modules.music.models import Track
from peacemusic.modules.music.recovery import PlaybackRecoveryService


def test_ytdlp_resolver_enforces_trusted_url_domains() -> None:
    resolver = YtDlpMediaResolver(allowed_domains=("example.test",))

    assert resolver._normalize_target("https://example.test/video") == (
        "https://example.test/video"
    )
    assert resolver._normalize_target("ambient piano") == "ytsearch1:ambient piano"

    with pytest.raises(ValidationError, match="domain"):
        resolver._normalize_target("https://untrusted.test/video")


def test_ytdlp_resolver_passes_configured_cookies_file_to_yt_dlp(
    tmp_path, monkeypatch
) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    resolver = YtDlpMediaResolver(cookies_file=str(cookie_file))
    options_seen: list[dict[str, object]] = []

    class YoutubeDL:
        def __init__(self, options) -> None:
            options_seen.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _target, download):
            assert download is False
            return {
                "title": "Example",
                "webpage_url": "https://example.test/video",
                "url": "https://cdn.example.test/audio",
            }

    yt_dlp = types.ModuleType("yt_dlp")
    yt_dlp.YoutubeDL = YoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", yt_dlp)

    resolver._extract("https://example.test/video")

    assert options_seen[0]["cookiefile"] == str(cookie_file)


def test_ytdlp_resolver_enables_external_youtube_js_components(monkeypatch) -> None:
    options_seen: list[dict[str, object]] = []

    class YoutubeDL:
        def __init__(self, options) -> None:
            options_seen.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _target, download):
            assert download is False
            return {
                "title": "Example",
                "webpage_url": "https://youtube.com/watch?v=1",
                "url": "https://cdn.example.test/audio",
            }

    yt_dlp = types.ModuleType("yt_dlp")
    yt_dlp.YoutubeDL = YoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", yt_dlp)

    YtDlpMediaResolver()._extract("https://youtube.com/watch?v=1")

    assert options_seen[0]["remote_components"] == ["ejs:github"]


def test_ytdlp_resolver_accepts_comma_separated_remote_components(
    monkeypatch,
) -> None:
    options_seen: list[dict[str, object]] = []

    class YoutubeDL:
        def __init__(self, options) -> None:
            options_seen.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _target, download):
            assert download is False
            return {
                "title": "Example",
                "webpage_url": "https://youtube.com/watch?v=1",
                "url": "https://cdn.example.test/audio",
            }

    yt_dlp = types.ModuleType("yt_dlp")
    yt_dlp.YoutubeDL = YoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", yt_dlp)

    YtDlpMediaResolver(
        remote_components="ejs:github, ejs:npm",
    )._extract("https://youtube.com/watch?v=1")

    assert options_seen[0]["remote_components"] == ["ejs:github", "ejs:npm"]


def test_ytdlp_metadata_is_translated_to_domain_model() -> None:
    media = YtDlpMediaResolver._to_media(
        {
            "title": "Example",
            "webpage_url": "https://example.test/video",
            "duration": 12.5,
            "uploader": "Artist",
            "url": "https://cdn.example.test/audio",
            "http_headers": {
                "User-Agent": "ExampleBrowser/1.0",
                "Referer": "https://example.test/",
            },
        }
    )

    assert media.title == "Example"
    assert media.duration == 12
    assert media.stream_url == "https://cdn.example.test/audio"
    assert media.http_headers == (
        ("Referer", "https://example.test/"),
        ("User-Agent", "ExampleBrowser/1.0"),
    )

    with pytest.raises(MediaExtractionError, match="no source"):
        YtDlpMediaResolver._to_media({"title": "No URL"})


def test_ytdlp_rejects_metadata_without_a_direct_stream() -> None:
    with pytest.raises(MediaExtractionError, match="direct stream"):
        YtDlpMediaResolver._to_media(
            {
                "title": "Example",
                "webpage_url": "https://example.test/video",
            }
        )


def test_ytdlp_expands_flat_search_results(monkeypatch) -> None:
    calls: list[str] = []
    options_seen: list[dict[str, object]] = []

    class YoutubeDL:
        def __init__(self, options) -> None:
            options_seen.append(options)
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, target, download):
            assert download is False
            calls.append(target)
            if target.startswith("ytsearch"):
                return {
                    "entries": [
                        {
                            "title": "Example",
                            "webpage_url": "https://youtube.com/watch?v=1",
                        }
                    ]
                }
            return {
                "title": "Example",
                "webpage_url": target,
                "url": "https://cdn.example.test/audio",
            }

    yt_dlp = types.ModuleType("yt_dlp")
    yt_dlp.YoutubeDL = YoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", yt_dlp)

    monkeypatch.setenv("YTDL_POT_PROVIDER_URL", "http://pot-provider:4416")
    data = YtDlpMediaResolver()._extract("ytsearch1:example")

    assert data["url"] == "https://cdn.example.test/audio"
    assert options_seen[0]["format"] == "bestaudio/best"
    assert options_seen[0]["extractor_args"] == {
        "youtubepot-bgutilhttp": {"base_url": "http://pot-provider:4416"}
    }
    assert calls == [
        "ytsearch1:example",
        "https://youtube.com/watch?v=1",
    ]


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
                "url": "https://cdn.example.test/audio",
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


def test_ytdlp_resolver_translates_provider_failures_and_counts_errors(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        metrics = MetricsRegistry()
        resolver = YtDlpMediaResolver(
            allowed_domains=("example.test",), metrics=metrics
        )

        def extract(_target: str):
            raise RuntimeError("provider failed")

        resolver._extract = extract  # type: ignore[method-assign]

        async def immediate_to_thread(function, *args):
            return function(*args)

        monkeypatch.setattr(
            "peacemusic.infrastructure.media.ytdlp.asyncio.to_thread",
            immediate_to_thread,
        )
        with pytest.raises(MediaExtractionError):
            await resolver.resolve("https://example.test/video")
        assert "peacemusic_ytdlp_errors_total 1" in metrics.render()

    asyncio.run(scenario())


def test_exception_description_preserves_wrapped_provider_reason() -> None:
    provider_error = RuntimeError("HTTP 403: signature challenge failed")
    wrapped = MediaExtractionError("yt-dlp could not resolve the query")
    wrapped.__cause__ = provider_error

    description = describe_exception(wrapped)

    assert "yt-dlp could not resolve the query" in description
    assert "HTTP 403: signature challenge failed" in description

    secret = describe_exception(RuntimeError("request failed api_key=hidden-value"))
    assert "api_key=[redacted]" in secret
    assert "hidden-value" not in secret


def test_ffmpeg_factory_builds_bounded_source_and_cleans_it(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Raw:
        def read(self):
            return b"first audio frame"

        def cleanup(self):
            calls.append(("cleanup", {}))

    class Wrapped:
        def __init__(self, raw, *, volume):
            self.raw = raw
            self.volume = volume

    def build(source, **kwargs):
        calls.append((source, kwargs))
        return Raw()

    monkeypatch.setattr(discord, "FFmpegPCMAudio", build)
    monkeypatch.setattr(discord, "PCMVolumeTransformer", Wrapped)

    async def scenario() -> None:
        source = await FFmpegAudioSourceFactory().create(
            Track(
                "song",
                "https://example.test/video",
                1,
                stream_url="https://cdn.example.test/audio",
                http_headers=(("User-Agent", "ExampleBrowser/1.0"),),
            ),
            start_seconds=9,
        )
        assert source.volume == 0.7
        cleanup_audio_source(source.raw)
        with pytest.raises(PlaybackError):
            await FFmpegAudioSourceFactory().create(Track("bad", "", 1))

    asyncio.run(scenario())
    before_options = calls[0][1]["before_options"]
    assert "-reconnect 1" in before_options
    assert "-reconnect_streamed 1" in before_options
    assert "-reconnect_delay_max 5" in before_options
    assert "-reconnect_on_network_error 1" in before_options
    assert "-reconnect_on_http_error 4xx,5xx" in before_options
    assert "-headers" in before_options
    assert "User-Agent: ExampleBrowser/1.0" in before_options
    assert before_options.endswith("-ss 9")
    assert calls[-1][0] == "cleanup"
