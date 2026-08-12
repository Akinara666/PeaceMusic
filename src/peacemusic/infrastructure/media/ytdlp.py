"""Bounded yt-dlp media resolution outside the asyncio event loop."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse
from typing import Any

from peacemusic.core.errors import MediaExtractionError, ValidationError
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
    ) -> None:
        if max_concurrent < 1 or timeout_seconds <= 0 or max_search_results < 1:
            raise ValueError("Invalid yt-dlp execution limits")
        self._options = dict(ytdl_options or {})
        self._allowed_domains = tuple(
            domain.lower().lstrip(".") for domain in allowed_domains
        )
        self._timeout_seconds = timeout_seconds
        self._max_search_results = max_search_results
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def resolve(self, query: str) -> ResolvedMedia:
        normalized = query.strip()
        if not normalized:
            raise ValidationError("Media query cannot be empty")
        target = self._normalize_target(normalized)
        async with self._semaphore:
            try:
                data = await asyncio.wait_for(
                    asyncio.to_thread(self._extract, target),
                    timeout=self._timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise MediaExtractionError("Media extraction timed out") from exc
            except MediaExtractionError:
                raise
            except Exception as exc:  # noqa: BLE001 - translate adapter errors
                raise MediaExtractionError("Media extraction failed") from exc
        return self._to_media(data)

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
                "quiet": True,
                "no_warnings": True,
            }
        )
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
            return first
        return result

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
        duration = data.get("duration")
        return ResolvedMedia(
            title=title,
            source_url=source_url,
            webpage_url=data.get("webpage_url"),
            thumbnail=data.get("thumbnail"),
            uploader=data.get("uploader") or data.get("channel"),
            duration=int(duration) if isinstance(duration, (int, float)) else None,
            stream_url=data.get("url"),
        )
