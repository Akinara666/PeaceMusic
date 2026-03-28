from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import shlex
import time as time_module
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Deque, Optional
from urllib.parse import urlparse

import discord
import yt_dlp as youtube_dl
from discord.ext import commands, tasks
from yt_dlp.utils import DownloadError

from config import MUSIC_DIRECTORY, YTDL_OPTIONS, FFMPEG_OPTIONS

logger = logging.getLogger(__name__)

MUSIC_DIRECTORY_PATH = Path(MUSIC_DIRECTORY)
MUSIC_DIRECTORY_PATH.mkdir(parents=True, exist_ok=True)
STREAM_SOURCE_MAX_AGE_SECONDS = 180


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def format_duration(duration_seconds: float | int | None) -> str:
    if duration_seconds is None:
        return "00:00"
    try:
        total_seconds = int(float(duration_seconds))
    except (TypeError, ValueError):
        return "00:00"
    if total_seconds < 1:
        return "00:00"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def parse_time(time_str: str) -> int:
    parts = time_str.split(":")
    try:
        values = list(map(int, parts))
    except ValueError as exc:
        raise ValueError(
            "Invalid time format. Use seconds, MM:SS, or HH:MM:SS."
        ) from exc
    if any(value < 0 for value in values):
        raise ValueError("Time must be positive.")
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        minutes, seconds = values
        return minutes * 60 + seconds
    if len(values) == 3:
        hours, minutes, seconds = values
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError("Invalid time format. Use seconds, MM:SS, or HH:MM:SS.")


SOUNDCLOUD_DOMAINS = ("soundcloud.com", "on.soundcloud.com")
SOUNDCLOUD_QUERY_PREFIXES = ("sc ", "soundcloud ")
SOUNDCLOUD_QUERY_PREFIXES_WITH_COLON = ("sc:", "soundcloud:")
YOUTUBE_DOMAINS = ("youtube.com", "youtu.be", "music.youtube.com")


def _looks_like_url(query: str) -> bool:
    lowered = query.lower()
    return lowered.startswith(("http://", "https://"))


def _is_youtube_url(url: str) -> bool:
    if not _looks_like_url(url):
        return False
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in YOUTUBE_DOMAINS
    )


def _is_youtube_hls_entry(entry: dict) -> bool:
    webpage_url = entry.get("webpage_url", "")
    extractor = (entry.get("extractor") or "").lower()
    protocol = (entry.get("protocol") or "").lower()
    manifest_url = (entry.get("manifest_url") or "").lower()
    playback_url = (entry.get("url") or "").lower()

    is_youtube = _is_youtube_url(webpage_url) or extractor in {"youtube", "youtube:tab"}
    if not is_youtube:
        return False
    return any(
        marker in value
        for value in (protocol, manifest_url, playback_url)
        for marker in ("m3u8", ".m3u8", "playlist/index.m3u8")
    )


def normalize_audio_query(query: str) -> str:
    """Normalize user input to support explicit SoundCloud searches and URLs."""
    query = query.strip()
    if not query:
        return query

    lowered = query.lower()

    for prefix in SOUNDCLOUD_QUERY_PREFIXES:
        if lowered.startswith(prefix):
            rest = query[len(prefix) :].strip()
            if rest:
                return f"scsearch1:{rest}"
            return query

    for prefix in SOUNDCLOUD_QUERY_PREFIXES_WITH_COLON:
        if lowered.startswith(prefix):
            rest = query[len(prefix) :].strip()
            if rest:
                return f"scsearch1:{rest}"
            return query

    if lowered.startswith("scsearch"):
        return query

    if not _looks_like_url(query):
        stripped_query = query[4:] if lowered.startswith("www.") else query
        if " " not in stripped_query and any(
            domain in stripped_query.lower() for domain in SOUNDCLOUD_DOMAINS
        ):
            return f"https://{query}"

    return query


def is_soundcloud_query(query: str) -> bool:
    lowered = query.lower()
    if lowered.startswith("scsearch"):
        return True
    if _looks_like_url(query):
        parsed = urlparse(query)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in SOUNDCLOUD_DOMAINS
        )
    return False


def build_ffmpeg_options(
    stream: bool,
    *,
    seek: Optional[int] = None,
    user_agent: Optional[str] = None,
    youtube_hls: bool = False,
) -> dict[str, str]:
    if stream:
        before_key = (
            "before_options_stream_youtube_hls"
            if youtube_hls
            else "before_options_stream"
        )
        before = FFMPEG_OPTIONS[before_key]
        # Inject dynamic user agent if provided
        if user_agent:
            before += f" -user_agent {shlex.quote(user_agent)}"
    else:
        before = FFMPEG_OPTIONS["before_options_file"]

    if seek is not None and seek > 0:
        before = f"-ss {seek} {before}"
    return {
        "before_options": before,
        "options": FFMPEG_OPTIONS["options"],
    }


INFO_CACHE_TTL_SECONDS = 900
_info_cache: dict[str, tuple[float, dict]] = {}


def _create_ytdl() -> youtube_dl.YoutubeDL:
    return youtube_dl.YoutubeDL(dict(YTDL_OPTIONS))


def _extract_info_sync(url: str, *, download: bool) -> dict:
    return _create_ytdl().extract_info(url, download=download)


def _prepare_filename(entry: dict) -> str:
    return _create_ytdl().prepare_filename(entry)


async def _probe_info(
    url: str, *, loop: Optional[asyncio.AbstractEventLoop] = None
) -> dict:
    """Быстрое получение метаданных без скачивания, с кэшем."""
    loop = loop or asyncio.get_running_loop()
    cache_key = f"1:{url}"
    cached = _info_cache.get(cache_key)
    now = time_module.monotonic()
    if cached and (now - cached[0]) < INFO_CACHE_TTL_SECONDS:
        return cached[1]

    start = time_module.monotonic()
    data = await loop.run_in_executor(None, lambda: _extract_info_sync(url, download=False))
    _info_cache[cache_key] = (time_module.monotonic(), data)
    logger.debug("yt_dlp probe took %.2fs for %s", time_module.monotonic() - start, url)
    return data


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(
        self,
        source: discord.AudioSource,
        *,
        data: dict,
        stream: bool,
        local_path: Optional[Path] = None,
        volume: float = 1.0,
        on_chunk: Optional[Callable[[], None]] = None,
    ):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Untitled")
        self.url = data.get("url")
        self.webpage_url = data.get("webpage_url", "")
        self.thumbnail = data.get("thumbnail", "")
        self.uploader = data.get("uploader", "Unknown artist")
        self.duration = data.get("duration")
        self.local_path = local_path
        self.is_stream = stream
        self.is_youtube_hls = _is_youtube_hls_entry(data)
        self.user_agent = data.get("http_headers", {}).get("User-Agent")
        self._on_chunk = on_chunk

    def read(self) -> bytes:
        data = super().read()
        if data and self._on_chunk:
            with contextlib.suppress(Exception):
                self._on_chunk()
        return data

    @classmethod
    async def from_url(
        cls,
        url: str,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        stream: bool = True,
        on_chunk: Optional[Callable[[], None]] = None,
        start_at: Optional[int] = None,
        volume: float = 1.0,
    ) -> list["YTDLSource"]:
        loop = loop or asyncio.get_running_loop()

        cache_key = f"{int(stream)}:{url}"
        cached = _info_cache.get(cache_key)
        now = time_module.monotonic()
        use_cache = stream

        if use_cache and cached and (now - cached[0]) < INFO_CACHE_TTL_SECONDS:
            data = cached[1]
            logger.debug("yt_dlp extract_info cache hit for %s", url)
        else:
            start_time = time_module.monotonic()
            data = await loop.run_in_executor(
                None, lambda: _extract_info_sync(url, download=not stream)
            )
            elapsed = time_module.monotonic() - start_time
            if use_cache:
                _info_cache[cache_key] = (time_module.monotonic(), data)
            logger.debug("yt_dlp extract_info took %.2fs for %s", elapsed, url)

        entries = data.get("entries") or [data]

        sources: list[YTDLSource] = []
        for entry in entries:
            if not entry:
                continue

            local_path: Optional[Path] = None
            if stream:
                playback_target = entry.get("url")
                if not playback_target:
                    continue
                http_headers = entry.get("http_headers", {})
                dynamic_user_agent = http_headers.get("User-Agent")
            else:
                filename = _prepare_filename(entry)
                local_path = Path(filename)
                playback_target = str(local_path)
                dynamic_user_agent = None

            ffmpeg_args = build_ffmpeg_options(
                stream,
                seek=start_at,
                user_agent=dynamic_user_agent,
                youtube_hls=_is_youtube_hls_entry(entry),
            )
            audio_source = discord.FFmpegPCMAudio(playback_target, **ffmpeg_args)
            sources.append(
                cls(
                    audio_source,
                    data=entry,
                    stream=stream,
                    local_path=local_path,
                    volume=volume,
                    on_chunk=on_chunk,
                )
            )
        return sources


@dataclass
class QueuedTrack:
    source: discord.AudioSource
    title: str
    requester: discord.abc.User
    stream_url: Optional[str] = None
    webpage_url: Optional[str] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    duration: Optional[int] = None
    local_path: Optional[Path] = None
    user_agent: Optional[str] = None
    channel: Optional[discord.abc.Messageable] = None
    reload_query: Optional[str] = None
    should_stream: bool = True
    is_youtube_hls: bool = False
    prepared_at_monotonic: float = field(default_factory=time_module.monotonic)


@dataclass(frozen=True)
class UserNotificationResult:
    text: str
    user_notified: bool = False


# ----------------------------------------------------------------------------
# Music Cog
# ----------------------------------------------------------------------------


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_client: Optional[discord.VoiceClient] = None
        self.queue: Deque[QueuedTrack] = deque()
        self.current: Optional[QueuedTrack] = None
        self._play_lock = asyncio.Lock()
        self._last_audio_time: Optional[float] = None
        self._track_start_monotonic: Optional[float] = None
        self._paused_at_monotonic: Optional[float] = None
        self._restart_lock = asyncio.Lock()
        self._suppressed_after_callbacks = 0
        self.loop_mode = "off"
        self._replay_track: Optional[QueuedTrack] = None
        self._volume = 1.0

        self.check_for_inactivity.start()
        self.monitor_stalled_playback.start()

    def cog_unload(self) -> None:
        self.check_for_inactivity.cancel()
        self.monitor_stalled_playback.cancel()

    def _cleanup_track_file(self, track: Optional[QueuedTrack]) -> None:
        if not track or not track.local_path:
            return
        try:
            track.local_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning(
                "Failed to delete downloaded track %s", track.local_path, exc_info=True
            )
        track.local_path = None

    def _cleanup_queue(self) -> None:
        for track in list(self.queue):
            self._cleanup_track_file(track)
        self.queue.clear()

    def _result(self, text: str, *, user_notified: bool = False) -> UserNotificationResult:
        return UserNotificationResult(text=text, user_notified=user_notified)

    def _truncate_message_content(self, content: Optional[str]) -> Optional[str]:
        if content is None or len(content) <= 2000:
            return content
        return f"{content[:1997]}..."

    async def _safe_channel_send(
        self,
        channel: Optional[discord.abc.Messageable],
        *,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
    ) -> bool:
        if channel is None:
            return False
        try:
            await channel.send(content=self._truncate_message_content(content), embed=embed)
            return True
        except discord.HTTPException:
            logger.warning("Failed to send message to channel", exc_info=True)
            return False

    async def _safe_reply(
        self,
        message: discord.Message,
        *,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
    ) -> bool:
        payload = self._truncate_message_content(content)
        try:
            await message.reply(content=payload, embed=embed)
            return True
        except discord.HTTPException:
            logger.warning("Failed to reply to message %s", getattr(message, "id", None), exc_info=True)
            return await self._safe_channel_send(message.channel, content=payload, embed=embed)

    async def _safe_reply_message(
        self,
        message: discord.Message,
        *,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
    ) -> Optional[discord.Message]:
        try:
            return await message.reply(
                content=self._truncate_message_content(content),
                embed=embed,
            )
        except discord.HTTPException:
            logger.warning(
                "Failed to send reply message for %s",
                getattr(message, "id", None),
                exc_info=True,
            )
            return None

    async def _safe_edit_message(
        self,
        target: Optional[discord.Message],
        *,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
    ) -> bool:
        if target is None:
            return False
        try:
            await target.edit(content=self._truncate_message_content(content), embed=embed)
            return True
        except discord.HTTPException:
            logger.warning("Failed to edit message %s", getattr(target, "id", None), exc_info=True)
            return False

    async def _safe_delete_message(self, target: Optional[discord.Message]) -> bool:
        if target is None:
            return False
        try:
            await target.delete()
            return True
        except discord.HTTPException:
            logger.warning("Failed to delete message %s", getattr(target, "id", None), exc_info=True)
            return False

    def _track_background_send(self, task: asyncio.Task[bool]) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            exc = task.exception()
            if exc is not None:
                logger.warning("Background channel send failed: %s", exc)

    def _dispatch_channel_send(
        self,
        channel: Optional[discord.abc.Messageable],
        *,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
    ) -> None:
        task = asyncio.create_task(
            self._safe_channel_send(channel, content=content, embed=embed)
        )
        task.add_done_callback(self._track_background_send)

    def _touch_audio_heartbeat(self) -> None:
        self._last_audio_time = time_module.monotonic()

    def _reset_playback_timers(self) -> None:
        self._track_start_monotonic = None
        self._paused_at_monotonic = None

    def _mark_playback_started(self, *, start_at: int = 0) -> None:
        self._track_start_monotonic = time_module.monotonic() - max(start_at, 0)
        self._paused_at_monotonic = None
        self._touch_audio_heartbeat()

    def _current_progress_seconds(self) -> int:
        if self._track_start_monotonic is None:
            return 0
        now = self._paused_at_monotonic or time_module.monotonic()
        return max(0, int(now - self._track_start_monotonic))

    def _suppress_after_callback_once(self) -> None:
        self._suppressed_after_callbacks += 1

    def _stop_voice_client_for_replace(self) -> None:
        if self.voice_client and (
            self.voice_client.is_playing() or self.voice_client.is_paused()
        ):
            self._suppress_after_callback_once()
            self.voice_client.stop()

    def _create_local_track_source(
        self,
        file_path: Path,
        *,
        seek: Optional[int] = None,
        on_chunk: Optional[Callable[[], None]] = None,
    ) -> discord.PCMVolumeTransformer:
        ffmpeg_args = build_ffmpeg_options(stream=False, seek=seek)
        audio_source = discord.FFmpegPCMAudio(str(file_path), **ffmpeg_args)
        transformer = discord.PCMVolumeTransformer(audio_source, volume=self._volume)
        if on_chunk is not None:
            original_read = transformer.read

            def _read_with_heartbeat() -> bytes:
                data = original_read()
                if data:
                    with contextlib.suppress(Exception):
                        on_chunk()
                return data

            transformer.read = _read_with_heartbeat  # type: ignore[assignment]
        return transformer

    def _build_queued_track(
        self,
        src: YTDLSource,
        *,
        requester: discord.abc.User,
        channel: Optional[discord.abc.Messageable],
        fallback_query: str,
        should_stream: bool,
    ) -> QueuedTrack:
        return QueuedTrack(
            source=src,
            title=src.title,
            requester=requester,
            stream_url=src.url if src.is_stream else None,
            webpage_url=src.webpage_url,
            thumbnail=src.thumbnail,
            uploader=src.uploader,
            duration=src.duration,
            local_path=src.local_path,
            user_agent=src.user_agent,
            channel=channel,
            reload_query=src.webpage_url or fallback_query,
            should_stream=should_stream,
            is_youtube_hls=src.is_youtube_hls,
        )

    # ------------------------------------------------------------------
    # Queue helpers
    # ------------------------------------------------------------------
    async def _ensure_voice_client(
        self, message: discord.Message
    ) -> Optional[discord.VoiceClient]:
        author = message.author
        if not author.voice or not author.voice.channel:
            return None

        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel != author.voice.channel:
                await self.voice_client.move_to(author.voice.channel)
        else:
            self.voice_client = await author.voice.channel.connect(timeout=15)
        return self.voice_client

    async def _refresh_track_source(
        self,
        track: QueuedTrack,
        *,
        seek: Optional[int] = None,
    ) -> bool:
        seek_seconds = max(0, seek or 0)

        if track.local_path and track.local_path.exists():
            track.source = self._create_local_track_source(
                track.local_path, seek=seek_seconds or None,
                on_chunk=self._touch_audio_heartbeat,
            )
            if not track.should_stream:
                track.stream_url = None
                track.user_agent = None
            track.prepared_at_monotonic = time_module.monotonic()
            return True

        target_query = track.reload_query or track.webpage_url or track.stream_url
        if not target_query:
            return False

        sources = await YTDLSource.from_url(
            target_query,
            loop=self.bot.loop,
            stream=track.should_stream,
            on_chunk=self._touch_audio_heartbeat,
            start_at=seek_seconds or None,
            volume=self._volume,
        )
        if not sources:
            return False

        new_source = sources[0]
        old_local_path = track.local_path
        track.source = new_source
        track.title = new_source.title or track.title
        track.stream_url = new_source.url if new_source.is_stream else None
        track.webpage_url = new_source.webpage_url or track.webpage_url
        track.thumbnail = new_source.thumbnail or track.thumbnail
        track.uploader = new_source.uploader or track.uploader
        track.duration = new_source.duration or track.duration
        track.local_path = new_source.local_path
        track.is_youtube_hls = new_source.is_youtube_hls
        track.user_agent = new_source.user_agent
        track.prepared_at_monotonic = time_module.monotonic()

        if old_local_path and old_local_path != track.local_path:
            with contextlib.suppress(FileNotFoundError, OSError):
                old_local_path.unlink()
        return True

    async def _play_track(
        self,
        track: QueuedTrack,
        *,
        description: str,
        color: discord.Color,
        start_at: int = 0,
        force_refresh: bool = False,
    ) -> bool:
        needs_refresh = start_at > 0 or force_refresh
        if (
            track.should_stream
            and track.reload_query
            and (time_module.monotonic() - track.prepared_at_monotonic)
            > STREAM_SOURCE_MAX_AGE_SECONDS
        ):
            needs_refresh = True

        if needs_refresh:
            refreshed = await self._refresh_track_source(
                track, seek=start_at or None
            )
            if not refreshed:
                return False

        self.current = track
        try:
            self.voice_client.play(track.source, after=self._after_playback)
        except Exception:
            if track.should_stream and track.reload_query and not needs_refresh:
                logger.warning("Retrying playback with a refreshed stream for %s", track.title)
                refreshed = await self._refresh_track_source(track, seek=start_at or None)
                if not refreshed:
                    return False
                try:
                    self.voice_client.play(track.source, after=self._after_playback)
                except Exception:
                    self.current = None
                    logger.exception("Failed to start playback for %s", track.title)
                    return False
            else:
                self.current = None
                logger.exception("Failed to start playback for %s", track.title)
                return False

        logger.info("Now playing: %s", track.title)
        self._mark_playback_started(start_at=start_at)

        if track.channel:
            embed = self._build_track_embed(track, color=color, description=description)
            self._dispatch_channel_send(track.channel, embed=embed)
        return True

    async def _start_next_track(self) -> None:
        if not self.voice_client or not self.voice_client.is_connected():
            return
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            return

        while True:
            if self._replay_track:
                track = self._replay_track
                self._replay_track = None
                description = "Повтор трека"
                color = discord.Color.purple()
                force_refresh = True
            elif self.queue:
                track = self.queue.popleft()
                description = "Сейчас играет"
                color = discord.Color.green()
                force_refresh = False
            else:
                self.current = None
                return

            try:
                played = await self._play_track(
                    track,
                    description=description,
                    color=color,
                    force_refresh=force_refresh,
                )
            except DownloadError as exc:
                logger.warning("Failed to prepare playback for %s: %s", track.title, exc)
                played = False
            except Exception:
                logger.exception("Unexpected playback setup error for %s", track.title)
                played = False

            if played:
                return

            self._cleanup_track_file(track)

    def _after_playback(self, error: Optional[Exception]) -> None:
        if self._suppressed_after_callbacks > 0:
            self._suppressed_after_callbacks -= 1
            return
        finished_track = self.current
        if error:
            logger.error("Playback error", exc_info=error)

        if finished_track and not error:
            if self.loop_mode == "track":
                self._replay_track = finished_track
            elif self.loop_mode == "queue":
                self._replay_track = None
                self.current = None
                self._reset_playback_timers()
                self.bot.loop.call_soon_threadsafe(
                    asyncio.create_task, self._requeue_and_continue(finished_track)
                )
                return
            else:
                self._cleanup_track_file(finished_track)
                self._replay_track = None
        else:
            if finished_track:
                self._cleanup_track_file(finished_track)
            self._replay_track = None

        self.current = None
        self._reset_playback_timers()
        self.bot.loop.call_soon_threadsafe(
            asyncio.create_task, self._start_next_track()
        )

    async def _requeue_and_continue(self, track: QueuedTrack) -> None:
        """Requeue the finished track and then start the next one.

        This ensures the requeue completes before ``_start_next_track``
        checks the queue, avoiding a race where the queue appears empty.
        """
        await self._requeue_lazy(track)
        await self._start_next_track()

    async def _requeue_lazy(self, track: QueuedTrack) -> None:
        requeued = False
        try:
            if track.local_path and track.local_path.exists():
                new_track = QueuedTrack(
                    source=self._create_local_track_source(
                        track.local_path, on_chunk=self._touch_audio_heartbeat
                    ),
                    title=track.title,
                    requester=track.requester,
                    stream_url=None,
                    webpage_url=track.webpage_url,
                    thumbnail=track.thumbnail,
                    uploader=track.uploader,
                    duration=track.duration,
                    local_path=track.local_path,
                    user_agent=None,
                    channel=track.channel,
                    reload_query=track.reload_query,
                    should_stream=track.should_stream,
                    is_youtube_hls=track.is_youtube_hls,
                )
                self.queue.append(new_track)
                track.local_path = None
                requeued = True
                return

            target_query = track.reload_query or track.webpage_url or track.stream_url
            if not target_query:
                return

            sources = await YTDLSource.from_url(
                target_query,
                loop=self.bot.loop,
                stream=track.should_stream,
                on_chunk=self._touch_audio_heartbeat,
                volume=self._volume,
            )
            for src in sources:
                self.queue.append(
                    self._build_queued_track(
                        src,
                        requester=track.requester,
                        channel=track.channel,
                        fallback_query=target_query,
                        should_stream=track.should_stream,
                    )
                )
            requeued = bool(sources)
            if requeued:
                track.local_path = None
        except Exception as exc:
            logger.warning("Failed to requeue for loop: %s", exc)
        finally:
            if not requeued:
                self._cleanup_track_file(track)

    async def _restart_current_stream(self) -> None:
        if not self.voice_client or not self.current or not self.current.should_stream:
            return
        if self.current.local_path:
            return
        async with self._restart_lock:
            current_track = self.current
            if not current_track or current_track is not self.current:
                return
            target_url = (
                current_track.reload_query
                or current_track.webpage_url
                or current_track.stream_url
            )
            if not target_url:
                return
            seek_seconds = max(0, self._current_progress_seconds() - 2)
            logger.warning(
                "Playback stalled, attempting to restart stream for %s", target_url
            )
            try:
                refreshed = await self._refresh_track_source(
                    current_track, seek=seek_seconds
                )
            except DownloadError as exc:
                logger.warning("Failed to restart stream %s: %s", target_url, exc)
                return
            except Exception:
                logger.exception(
                    "Unexpected error during stream restart for %s", target_url
                )
                return

            if (
                not refreshed
                or current_track is not self.current
                or not self.voice_client
                or not self.voice_client.is_connected()
            ):
                return

            self._stop_voice_client_for_replace()
            try:
                self.voice_client.play(current_track.source, after=self._after_playback)
            except Exception:
                logger.exception("Failed to restart playback for %s", current_track.title)
                return
            self._mark_playback_started(start_at=seek_seconds)

    def _build_track_embed(
        self,
        track: QueuedTrack,
        *,
        color: discord.Color,
        description: str = "Трек добавлен в очередь",
    ) -> discord.Embed:
        embed = discord.Embed(
            title=track.title,
            url=track.webpage_url or None,
            description=description,
            color=color,
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        if track.requester:
            embed.set_author(
                name=track.requester.display_name,
                icon_url=track.requester.display_avatar.url,
            )
        if track.uploader:
            embed.add_field(name="Автор", value=track.uploader, inline=True)
        if track.duration:
            embed.add_field(
                name="Длительность", value=format_duration(track.duration), inline=True
            )
        embed.set_footer(text="Приятного прослушивания!")
        return embed

    # ------------------------------------------------------------------
    # Public functions used by the AI cog
    async def play_func(
        self, message: discord.Message, song_name: str
    ) -> UserNotificationResult:
        async with self._play_lock:
            voice_client = await self._ensure_voice_client(message)
            if not voice_client:
                notified = await self._safe_reply(
                    message, content="Ты не подключен к голосовому каналу."
                )
                return self._result(
                    "Пользователь не в голосовом канале",
                    user_notified=notified,
                )

            tracks: list[QueuedTrack]
            normalized_query = normalize_audio_query(song_name)
            if normalized_query != song_name:
                logger.debug(
                    "Normalized audio query from %s to %s", song_name, normalized_query
                )

            # Hybrid strategy:
            # - SoundCloud: Download (stability)
            # - YouTube/Others: Stream (speed)
            is_soundcloud = is_soundcloud_query(normalized_query)
            should_stream = not is_soundcloud

            status_text = (
                "Скачиваю трек с SoundCloud..." if is_soundcloud else "Ищу трек..."
            )
            msg = await self._safe_reply_message(message, content=status_text)

            try:
                sources = await YTDLSource.from_url(
                    normalized_query,
                    loop=self.bot.loop,
                    stream=should_stream,
                    on_chunk=self._touch_audio_heartbeat,
                    volume=self._volume,
                )
            except DownloadError as exc:
                logger.warning("Failed to download track %s: %s", normalized_query, exc)
                notified = await self._safe_edit_message(
                    msg, content=f"Ошибка при поиске: {exc}"
                )
                if not notified:
                    notified = await self._safe_reply(
                        message, content=f"Ошибка при поиске: {exc}"
                    )
                return self._result("Ошибка поиска", user_notified=notified)
            except Exception as exc:  # noqa: BLE001
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.exception(
                    "Unexpected error while fetching track %s", normalized_query
                )
                notified = await self._safe_edit_message(
                    msg, content="Произошла непредвиденная ошибка."
                )
                if not notified:
                    notified = await self._safe_reply(
                        message, content="Произошла непредвиденная ошибка."
                    )
                return self._result("Ошибка поиска", user_notified=notified)

            tracks = [
                self._build_queued_track(
                    src,
                    requester=message.author,
                    channel=message.channel,
                    fallback_query=normalized_query,
                    should_stream=should_stream,
                )
                for src in sources
            ]

            if not tracks:
                notified = await self._safe_edit_message(
                    msg, content="Не удалось найти трек по этому запросу."
                )
                if not notified:
                    notified = await self._safe_reply(
                        message, content="Не удалось найти трек по этому запросу."
                    )
                return self._result("Трек не найден", user_notified=notified)

            for track in tracks:
                self.queue.append(track)

            # Check if we are starting playback immediately
            will_play_immediately = (
                voice_client.is_connected()
                and not voice_client.is_playing()
                and not voice_client.is_paused()
            )

            if will_play_immediately:
                # If playing immediately, `_start_next_track` will send the "Now Playing" embed.
                # We can delete the "Downloading..." temporary message to avoid double notifications.
                await self._safe_delete_message(msg)
                await self._start_next_track()
                user_notified = True
            else:
                # If adding to queue, show the "Added to queue" embed
                embed = self._build_track_embed(tracks[0], color=discord.Color.blue())
                user_notified = await self._safe_edit_message(msg, content=None, embed=embed)
                if not user_notified:
                    user_notified = await self._safe_reply(message, embed=embed)

            queued_titles = ", ".join(track.title for track in tracks)
            if len(tracks) > 1:
                return self._result(
                    f"Добавлено {len(tracks)} треков из плейлиста.",
                    user_notified=user_notified,
                )
            return self._result(
                f"Добавлено в очередь: {queued_titles}",
                user_notified=user_notified,
            )

    async def play_attachment_func(
        self, message: discord.Message, attachment: discord.Attachment
    ) -> UserNotificationResult:
        async with self._play_lock:
            voice_client = await self._ensure_voice_client(message)
            if not voice_client:
                notified = await self._safe_reply(
                    message, content="Ты не подключен к голосовому каналу."
                )
                return self._result(
                    "Пользователь не в голосовом канале",
                    user_notified=notified,
                )

            # Save file with unique name
            safe_filename = Path(attachment.filename).name
            file_path = MUSIC_DIRECTORY_PATH / f"{time_module.time_ns()}_{safe_filename}"

            try:
                await attachment.save(file_path)
            except Exception as exc:
                logger.warning("Failed to save attachment %s: %s", safe_filename, exc)
                notified = await self._safe_reply(
                    message, content="Ошибка сохранения файла"
                )
                return self._result(
                    "Ошибка сохранения файла",
                    user_notified=notified,
                )

            try:
                audio_source = self._create_local_track_source(
                    file_path, on_chunk=self._touch_audio_heartbeat
                )
            except Exception as exc:
                logger.error(
                    "Failed to create audio source for %s: %s", safe_filename, exc
                )
                with contextlib.suppress(OSError):
                    file_path.unlink()
                notified = await self._safe_reply(
                    message, content="Ошибка обработки аудиофайла"
                )
                return self._result(
                    "Ошибка обработки аудиофайла",
                    user_notified=notified,
                )

            track = QueuedTrack(
                source=audio_source,
                title=safe_filename,
                requester=message.author,
                local_path=file_path,
                webpage_url=attachment.url,
                channel=message.channel,
                should_stream=False,
            )

            self.queue.append(track)

            will_play_immediately = (
                voice_client.is_connected()
                and not voice_client.is_playing()
                and not voice_client.is_paused()
            )

            if will_play_immediately:
                await self._start_next_track()
                user_notified = True
            else:
                embed = self._build_track_embed(track, color=discord.Color.green())
                user_notified = await self._safe_reply(message, embed=embed)

            return self._result(
                f"Добавлено в очередь: {track.title}",
                user_notified=user_notified,
            )

    async def skip_func(self, message: discord.Message) -> UserNotificationResult:
        if not self.voice_client or (
            not self.voice_client.is_playing() and not self.voice_client.is_paused()
        ):
            notified = await self._safe_reply(message, content="Сейчас ничего не играет.")
            return self._result("Очередь не воспроизводится", user_notified=notified)

        skipped = self.current.title if self.current else "текущий трек"
        self.voice_client.stop()
        notified = await self._safe_reply(message, content=f"Пропускаю: {skipped}")
        return self._result(f"Пропущен трек: {skipped}", user_notified=notified)

    async def skip_by_name_func(
        self, message: discord.Message, song_name: str
    ) -> UserNotificationResult:
        lowercase_query = song_name.lower()
        if self.current and lowercase_query in self.current.title.lower():
            skipped_title = self.current.title
            if self.voice_client and (
                self.voice_client.is_playing() or self.voice_client.is_paused()
            ):
                self.voice_client.stop()
            notified = await self._safe_reply(
                message, content=f"Пропущен текущий трек: {skipped_title}"
            )
            return self._result(
                f"Пропущен текущий трек: {skipped_title}",
                user_notified=notified,
            )

        for track in list(self.queue):
            if lowercase_query in track.title.lower():
                self.queue.remove(track)
                self._cleanup_track_file(track)
                notified = await self._safe_reply(
                    message, content=f"Удалено из очереди: {track.title}"
                )
                return self._result(
                    f"Удалено из очереди: {track.title}",
                    user_notified=notified,
                )
        notified = await self._safe_reply(message, content="Такой трек не найден в очереди.")
        return self._result("Трек не найден", user_notified=notified)

    async def stop_func(self, message: discord.Message) -> UserNotificationResult:
        self.loop_mode = "off"
        self._replay_track = None
        self._cleanup_queue()
        current_track = self.current
        self.current = None
        self._reset_playback_timers()
        if self.voice_client and (
            self.voice_client.is_playing() or self.voice_client.is_paused()
        ):
            self._suppress_after_callback_once()
            self.voice_client.stop()
        self._cleanup_track_file(current_track)
        notified = await self._safe_reply(
            message, content="Очередь очищена и воспроизведение остановлено."
        )
        return self._result("Очередь очищена", user_notified=notified)

    async def summon_func(self, message: discord.Message) -> UserNotificationResult:
        voice_client = await self._ensure_voice_client(message)
        if not voice_client:
            notified = await self._safe_reply(
                message, content="Ты не подключен к голосовому каналу."
            )
            return self._result(
                "Пользователь не в голосовом канале",
                user_notified=notified,
            )
        notified = await self._safe_reply(message, content="Я уже с вами в канале!")
        return self._result("Бот в голосовом канале", user_notified=notified)

    async def disconnect_func(self, message: discord.Message) -> UserNotificationResult:
        self.loop_mode = "off"
        self._replay_track = None
        current_track = self.current
        self.current = None
        self._reset_playback_timers()
        self._cleanup_queue()
        if self.voice_client:
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self._suppress_after_callback_once()
                self.voice_client.stop()
            await self.voice_client.disconnect(force=True)
            self.voice_client = None
        self._cleanup_track_file(current_track)
        notified = await self._safe_reply(
            message, content="Отключилась от канала и очистила очередь."
        )
        return self._result("Бот отключён", user_notified=notified)

    async def seek_func(
        self, message: discord.Message, time: str
    ) -> UserNotificationResult:
        if (
            not self.voice_client
            or (
                not self.voice_client.is_playing() and not self.voice_client.is_paused()
            )
            or not self.current
        ):
            notified = await self._safe_reply(message, content="Сейчас ничего не играет.")
            return self._result("Нет трека для перемотки", user_notified=notified)

        try:
            seconds = parse_time(time)
        except ValueError:
            notified = await self._safe_reply(
                message, content="Неверный формат времени. Пример: 1:23 или 73"
            )
            return self._result("Некорректное время", user_notified=notified)

        if not self.current.stream_url and not self.current.local_path:
            notified = await self._safe_reply(
                message, content="Для этого трека перемотка недоступна."
            )
            return self._result("Перемотка недоступна", user_notified=notified)

        was_paused = self.voice_client.is_paused()
        try:
            refreshed = await self._refresh_track_source(self.current, seek=seconds)
        except DownloadError as exc:
            logger.warning("Failed to seek %s: %s", self.current.title, exc)
            notified = await self._safe_reply(
                message, content="Не удалось перемотать трек."
            )
            return self._result("Ошибка перемотки", user_notified=notified)
        except Exception:
            logger.exception("Unexpected seek error for %s", self.current.title)
            notified = await self._safe_reply(
                message, content="Не удалось перемотать трек."
            )
            return self._result("Ошибка перемотки", user_notified=notified)

        if not refreshed:
            notified = await self._safe_reply(
                message, content="Для этого трека перемотка недоступна."
            )
            return self._result("Перемотка недоступна", user_notified=notified)

        self._stop_voice_client_for_replace()
        try:
            self.voice_client.play(self.current.source, after=self._after_playback)
        except Exception:
            logger.exception("Failed to resume playback after seek for %s", self.current.title)
            notified = await self._safe_reply(
                message, content="Не удалось перемотать трек."
            )
            return self._result("Ошибка перемотки", user_notified=notified)
        self._mark_playback_started(start_at=seconds)
        if was_paused:
            self.voice_client.pause()
            self._paused_at_monotonic = time_module.monotonic()
        notified = await self._safe_reply(
            message, content=f"Перемотала на {format_duration(seconds)}"
        )
        return self._result(
            f"Перемотала на {format_duration(seconds)}",
            user_notified=notified,
        )

    async def pause_func(self, message: discord.Message) -> UserNotificationResult:
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self._paused_at_monotonic = time_module.monotonic()
            notified = await self._safe_reply(
                message, content="Воспроизведение приостановлено."
            )
            return self._result("Воспроизведение на паузе", user_notified=notified)
        return self._result("Ничего не играет")

    async def resume_func(self, message: discord.Message) -> UserNotificationResult:
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            if (
                self._paused_at_monotonic is not None
                and self._track_start_monotonic is not None
            ):
                self._track_start_monotonic += (
                    time_module.monotonic() - self._paused_at_monotonic
                )
            self._paused_at_monotonic = None
            self._touch_audio_heartbeat()
            notified = await self._safe_reply(
                message, content="Воспроизведение продолжено."
            )
            return self._result("Воспроизведение продолжено", user_notified=notified)
        return self._result("Нечего продолжать")

    async def now_playing_func(
        self, message: discord.Message
    ) -> UserNotificationResult:
        if (
            not self.voice_client
            or (
                not self.voice_client.is_playing()
                and not self.voice_client.is_paused()
            )
            or not self.current
        ):
            return self._result("Сейчас ничего не играет.")

        progress = self._current_progress_seconds()
        dur = self.current.duration
        dur_str = format_duration(dur) if dur else "Неизвестно"
        prog_str = format_duration(progress)

        return self._result(
            f"Сейчас играет: {self.current.title} (Прогресс: {prog_str} / {dur_str})"
        )

    async def get_queue_func(
        self, message: discord.Message
    ) -> UserNotificationResult:
        if not self.queue:
            return self._result("Очередь пуста.")
        
        lines = []
        for i, track in enumerate(self.queue, start=1):
            dur = format_duration(track.duration) if track.duration else "?:??"
            lines.append(f"{i}. {track.title} ({dur})")
            if i >= 20:
                lines.append("... и еще треки")
                break
        return self._result("\n".join(lines))

    async def shuffle_queue_func(
        self, message: discord.Message
    ) -> UserNotificationResult:
        if not self.queue:
            return self._result("Очередь пуста, нечего перемешивать.")
        queue_list = list(self.queue)
        random.shuffle(queue_list)
        self.queue.clear()
        self.queue.extend(queue_list)
        notified = await self._safe_reply(message, content="Очередь перемешана.")
        return self._result("Очередь перемешана", user_notified=notified)

    async def clear_queue_func(
        self, message: discord.Message
    ) -> UserNotificationResult:
        if not self.queue:
            return self._result("Очередь и так пуста.")
        self._cleanup_queue()
        if self.loop_mode == "queue":
            self.loop_mode = "off"
        notified = await self._safe_reply(
            message, content="Очередь очищена (текущий трек продолжает играть)."
        )
        return self._result("Очередь очищена", user_notified=notified)

    async def remove_from_queue_func(
        self, message: discord.Message, index: int
    ) -> UserNotificationResult:
        if not self.queue:
            return self._result("Очередь пуста.")
        if index < 1 or index > len(self.queue):
            return self._result(f"Неверный индекс. В очереди {len(self.queue)} треков.")
        
        track = self.queue[index - 1]
        del self.queue[index - 1]
        self._cleanup_track_file(track)
        notified = await self._safe_reply(
            message, content=f"Удалено из очереди: {track.title}"
        )
        return self._result(f"Удален трек: {track.title}", user_notified=notified)

    async def set_loop_mode_func(
        self, message: discord.Message, mode: str
    ) -> UserNotificationResult:
        mode = mode.lower()
        if mode not in ("off", "track", "queue"):
            return self._result(
                "Неизвестный режим. Используйте 'off', 'track' или 'queue'."
            )
        
        self.loop_mode = mode
        modes_tr = {"off": "Выключен", "track": "Текущий трек", "queue": "Вся очередь"}
        notified = await self._safe_reply(
            message, content=f"Режим повтора установлен на: {modes_tr[mode]}."
        )
        return self._result(f"Режим повтора: {mode}", user_notified=notified)

    async def set_volume_func(
        self, message: discord.Message, level: float
    ) -> UserNotificationResult:
        if level < 0.0 or level > 5.0:
            notified = await self._safe_reply(
                message, content="Громкость должна быть в диапазоне 0.0-5.0."
            )
            return self._result("Недопустимое значение громкости", user_notified=notified)

        self._volume = level
        if not self.voice_client:
            notified = await self._safe_reply(
                message,
                content=f"Громкость по умолчанию установлена на {int(level * 100)}%.",
            )
            return self._result(
                f"Громкость {int(level * 100)}%",
                user_notified=notified,
            )

        source = self.voice_client.source
        if hasattr(source, "volume"):
            source.volume = level
            notified = await self._safe_reply(
                message, content=f"Громкость установлена на {int(level * 100)}%."
            )
            return self._result(
                f"Громкость {int(level * 100)}%",
                user_notified=notified,
            )

        notified = await self._safe_reply(
            message,
            content=f"Громкость по умолчанию установлена на {int(level * 100)}%.",
        )
        return self._result(
            f"Громкость {int(level * 100)}%",
            user_notified=notified,
        )

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------
    @tasks.loop(seconds=20)
    async def monitor_stalled_playback(self) -> None:
        if not self.voice_client or not self.current:
            return
        if not self.voice_client.is_playing():
            return
        if self.current.local_path:
            return
        now = time_module.monotonic()
        last = self._last_audio_time or now
        if now - last > 25:
            await self._restart_current_stream()

    @monitor_stalled_playback.before_loop
    async def before_monitor_stalled_playback(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def check_for_inactivity(self) -> None:
        now = time_module.monotonic()
        if self.voice_client and self.voice_client.is_connected():
            if not self.voice_client.is_playing() and not self.voice_client.is_paused():
                last_time = self._last_audio_time or now
                if now - last_time > 1800:
                    await self.voice_client.disconnect(force=True)
                    self.voice_client = None
        if not self.voice_client or not self.voice_client.is_connected():
            self._cleanup_queue()
            self._cleanup_track_file(self.current)
            self.current = None
            self._replay_track = None
            self._reset_playback_timers()

    @check_for_inactivity.before_loop
    async def before_check_for_inactivity(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if not self.bot.user or member.id != self.bot.user.id:
            return
        if before.channel and after.channel is None:
            self.voice_client = None
            self._cleanup_queue()
            self._cleanup_track_file(self.current)
            self.current = None
            self._replay_track = None
            self._reset_playback_timers()
