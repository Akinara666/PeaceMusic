"""Discord FFmpeg audio-source adapter."""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

import discord

from peacemusic.core.errors import PlaybackError, describe_exception
from peacemusic.modules.music.models import Track


class FFmpegAudioSourceFactory:
    """Build and clean up Discord-compatible FFmpeg sources."""

    def __init__(
        self,
        *,
        executable: str = "ffmpeg",
        before_options: str = (
            "-nostdin -reconnect 1 -reconnect_streamed 1 "
            "-reconnect_delay_max 5 -reconnect_on_network_error 1 "
            "-reconnect_on_http_error 4xx,5xx"
        ),
        options: str = "-vn -sn -dn -loglevel warning",
        probe_timeout_seconds: float = 10.0,
    ) -> None:
        if probe_timeout_seconds <= 0:
            raise ValueError("probe_timeout_seconds must be positive")
        self._executable = executable
        self._before_options = before_options
        self._options = options
        self._probe_timeout_seconds = probe_timeout_seconds

    async def create(
        self, track: Track, *, start_seconds: int = 0
    ) -> discord.AudioSource:
        source = track.stream_url
        if not source:
            raise PlaybackError("Track has no resolved audio stream")
        if start_seconds < 0:
            raise PlaybackError("FFmpeg start position cannot be negative")
        raw_source: Any | None = None
        try:
            before_options = self._before_options
            if track.http_headers:
                headers = "".join(
                    f"{name}: {value}\r\n" for name, value in track.http_headers
                )
                before_options = f"{before_options} -headers {shlex.quote(headers)}"
            if start_seconds:
                before_options = f"{before_options} -ss {start_seconds}"
            raw_source = discord.FFmpegPCMAudio(
                source,
                executable=self._executable,
                before_options=before_options,
                options=self._options,
            )
            first_frame = await self._probe(raw_source)
            if first_frame is None:
                return discord.PCMVolumeTransformer(raw_source, volume=0.7)
            return discord.PCMVolumeTransformer(
                _PreloadedAudioSource(raw_source, first_frame), volume=0.7
            )
        except asyncio.TimeoutError as exc:
            cleanup_audio_source(raw_source)
            raise PlaybackError("Audio stream did not become readable in time") from exc
        except PlaybackError:
            cleanup_audio_source(raw_source)
            raise
        except Exception as exc:  # noqa: BLE001 - normalize FFmpeg failures
            cleanup_audio_source(raw_source)
            raise PlaybackError(
                f"Audio stream could not be started: {describe_exception(exc)}"
            ) from exc

    async def _probe(self, source: Any) -> bytes | None:
        """Read one frame so immediate HTTP/FFmpeg failures reach the caller."""

        stdout = getattr(source, "_stdout", None)
        fileno = getattr(stdout, "fileno", None)
        if fileno is None:
            return None
        try:
            descriptor = fileno()
        except (OSError, ValueError):
            return None

        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        loop.add_reader(descriptor, ready.set_result, None)
        try:
            await asyncio.wait_for(ready, timeout=self._probe_timeout_seconds)
        finally:
            loop.remove_reader(descriptor)

        frame = source.read()
        if not frame:
            raise PlaybackError("Audio stream returned no data")
        return frame


class _PreloadedAudioSource(discord.AudioSource):
    """Replay the probe frame before reading the live FFmpeg source."""

    def __init__(self, source: discord.AudioSource, first_frame: bytes) -> None:
        self._source = source
        self._first_frame = first_frame

    def read(self) -> bytes:
        if self._first_frame is not None:
            frame = self._first_frame
            self._first_frame = None
            return frame
        return self._source.read()

    def is_opus(self) -> bool:
        return self._source.is_opus()

    def cleanup(self) -> None:
        cleanup_audio_source(self._source)


def cleanup_audio_source(source: Any) -> None:
    """Release an adapter-owned source without leaking FFmpeg subprocesses."""

    cleanup = getattr(source, "cleanup", None)
    if cleanup is not None:
        cleanup()
