"""Discord FFmpeg audio-source adapter."""

from __future__ import annotations

from typing import Any

import discord

from peacemusic.core.errors import PlaybackError
from peacemusic.modules.music.models import Track


class FFmpegAudioSourceFactory:
    """Build and clean up Discord-compatible FFmpeg sources."""

    def __init__(
        self,
        *,
        executable: str = "ffmpeg",
        before_options: str = "-nostdin",
        options: str = "-vn -sn -dn -loglevel warning",
    ) -> None:
        self._executable = executable
        self._before_options = before_options
        self._options = options

    async def create(
        self, track: Track, *, start_seconds: int = 0
    ) -> discord.AudioSource:
        source = track.stream_url or track.source_url
        if not source:
            raise PlaybackError("Track has no FFmpeg source")
        if start_seconds < 0:
            raise PlaybackError("FFmpeg start position cannot be negative")
        try:
            before_options = self._before_options
            if start_seconds:
                before_options = f"{before_options} -ss {start_seconds}"
            raw_source = discord.FFmpegPCMAudio(
                source,
                executable=self._executable,
                before_options=before_options,
                options=self._options,
            )
            return discord.PCMVolumeTransformer(raw_source, volume=0.7)
        except (OSError, ValueError) as exc:
            raise PlaybackError("FFmpeg audio source could not be created") from exc


def cleanup_audio_source(source: Any) -> None:
    """Release an adapter-owned source without leaking FFmpeg subprocesses."""

    cleanup = getattr(source, "cleanup", None)
    if cleanup is not None:
        cleanup()
