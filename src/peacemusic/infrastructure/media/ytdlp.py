"""Bounded yt-dlp media resolution outside the asyncio event loop."""

from __future__ import annotations

import asyncio
import os
import time
from urllib.parse import urlparse
from typing import Any

from peacemusic.core.errors import MediaExtractionError, ValidationError
from peacemusic.core.metrics import MetricsRegistry
from peacemusic.modules.music.models import ResolvedMedia


class YtDlpMediaResolver:
    """Resolve one search result or trusted URL using yt-dlp in a worker thread."""

    def __init__(
        self,
        *,
        ytdl_options: dict[str, Any] | None = None,
        allowed_domains: tuple[str, ...] = (
            "youtube.com",
            "youtu.be",
            "music.youtube.com",
            "soundcloud.com",
            "on.soundcloud.com",
        ),
        max_concurrent: int = 2,
        timeout_seconds: float = 30.0,
        max_search_results: int = 1,
        metrics: MetricsRegistry | None = None,
        pot_provider_url: str | None = None,
    ) -> None:
        if max_concurrent < 1 or timeout_seconds <= 0 or max_search_results < 1:
            raise ValueError("Invalid yt-dlp execution limits")
        self._options = dict(ytdl_options or {})
        self._allowed_domains = tuple(
            domain.lower().lstrip(".") for domain in allowed_domains
        )
        self._timeout_seconds = timeout_seconds
        self._max_search_results = max_search_results
        self._metrics = metrics
        self._pot_provider_url = pot_provider_url or os.getenv("YTDL_POT_PROVIDER_URL")
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def resolve(self, query: str) -> ResolvedMedia:
        normalized = query.strip()
        if not normalized:
            raise ValidationError("Media query cannot be empty")
        target = self._normalize_target(normalized)
        started = time.monotonic()
        self._increment_metric("peacemusic_ytdlp_requests_total")
        async with self._semaphore:
            try:
                data = await asyncio.wait_for(
                    asyncio.to_thread(self._extract, target),
                    timeout=self._timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                self._increment_metric("peacemusic_ytdlp_errors_total")
                raise MediaExtractionError("Media extraction timed out") from exc
            except MediaExtractionError:
                self._increment_metric("peacemusic_ytdlp_errors_total")
                raise
            except Exception as exc:  # noqa: BLE001 - translate adapter errors
                self._increment_metric("peacemusic_ytdlp_errors_total")
                raise MediaExtractionError("Media extraction failed") from exc
            finally:
                self._observe_metric(
                    "peacemusic_ytdlp_duration_seconds",
                    time.monotonic() - started,
                )
        return self._to_media(data)

    def _increment_metric(self, name: str) -> None:
        if self._metrics is not None:
            self._metrics.increment(name)

    def _observe_metric(self, name: str, value: float) -> None:
        if self._metrics is not None:
            self._metrics.observe(name, value)

    def _extract(self, target: str) -> dict[str, Any]:
        try:
            import yt_dlp
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise MediaExtractionError("yt-dlp is not installed") from exc

        options = dict(self._options)
        options.update(
            {
                "noplaylist": True,
                "playlistend": self._max_search_results,
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
            }
        )
        if self._pot_provider_url:
            extractor_args = dict(options.get("extractor_args") or {})
            pot_args = dict(extractor_args.get("youtubepot-bgutilhttp") or {})
            pot_args["base_url"] = self._pot_provider_url
            extractor_args["youtubepot-bgutilhttp"] = pot_args
            options["extractor_args"] = extractor_args
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                result = downloader.extract_info(target, download=False)
        except Exception as exc:  # noqa: BLE001 - normalize yt-dlp exceptions
            raise MediaExtractionError("yt-dlp could not resolve the query") from exc
        if not isinstance(result, dict):
            raise MediaExtractionError("yt-dlp returned invalid metadata")
        entries = result.get("entries")
        if entries:
            first = next((entry for entry in entries if isinstance(entry, dict)), None)
            if first is None:
                raise MediaExtractionError("yt-dlp returned no playable result")
            if not self._has_direct_stream(first):
                webpage_url = first.get("webpage_url") or first.get("original_url")
                if isinstance(webpage_url, str) and webpage_url:
                    try:
                        expanded = downloader.extract_info(webpage_url, download=False)
                    except Exception as exc:  # noqa: BLE001 - normalize yt-dlp errors
                        raise MediaExtractionError(
                            "yt-dlp could not resolve the selected media stream"
                        ) from exc
                    if isinstance(expanded, dict):
                        return expanded
            return first
        return result

    @staticmethod
    def _has_direct_stream(data: dict[str, Any]) -> bool:
        stream_url = data.get("url") or data.get("manifest_url")
        webpage_url = data.get("webpage_url") or data.get("original_url")
        return (
            isinstance(stream_url, str)
            and bool(stream_url)
            and stream_url != webpage_url
        )

    def _normalize_target(self, query: str) -> str:
        parsed = urlparse(query)
        if parsed.scheme in {"http", "https"}:
            host = (parsed.hostname or "").lower().rstrip(".")
            if not host or not any(
                host == domain or host.endswith(f".{domain}")
                for domain in self._allowed_domains
            ):
                raise ValidationError("Media URL domain is not allowed")
            return query
        if parsed.scheme:
            raise ValidationError("Only HTTP(S) media URLs are supported")
        return f"ytsearch{self._max_search_results}:{query}"

    @staticmethod
    def _to_media(data: dict[str, Any]) -> ResolvedMedia:
        title = str(data.get("title") or "Untitled track").strip()
        source_url = data.get("webpage_url") or data.get("original_url")
        if not isinstance(source_url, str) or not source_url:
            raise MediaExtractionError("Resolved media has no source URL")
        stream_url = data.get("url") or data.get("manifest_url")
        if (
            not isinstance(stream_url, str)
            or not stream_url
            or stream_url == source_url
        ):
            raise MediaExtractionError("Resolved media has no direct stream URL")
        duration = data.get("duration")
        return ResolvedMedia(
            title=title,
            source_url=source_url,
            webpage_url=data.get("webpage_url"),
            thumbnail=data.get("thumbnail"),
            uploader=data.get("uploader") or data.get("channel"),
            duration=int(duration) if isinstance(duration, (int, float)) else None,
            stream_url=stream_url,
        )
