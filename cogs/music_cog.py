from __future__ import annotations

import asyncio
import contextlib
import logging
import queue as queue_module
import random
import shlex
import threading
import time as time_module
from collections import OrderedDict, deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Deque, Optional
from urllib.parse import urlparse

import discord
from discord import app_commands
import yt_dlp as youtube_dl
from discord.ext import commands, tasks
from yt_dlp.utils import DownloadError

from config import (
    FFMPEG_OPTIONS,
    MEDIA_ALLOWED_DOMAINS,
    MUSIC_ATTACHMENT_MAX_BYTES,
    MUSIC_DIRECTORY,
    MUSIC_QUEUE_MAX_SIZE,
    MUSIC_STREAM_BUFFER_SECONDS,
    MUSIC_STREAM_RESTART_COOLDOWN_SECONDS,
    MUSIC_STREAM_STALL_TIMEOUT_SECONDS,
    MUSIC_STREAM_START_BUFFER_SECONDS,
    MUSIC_STREAM_START_TIMEOUT_SECONDS,
    MUSIC_STREAM_UNDERRUN_GRACE_SECONDS,
    YTDL_OPTIONS,
)

logger = logging.getLogger(__name__)

MUSIC_DIRECTORY_PATH = Path(MUSIC_DIRECTORY)
MUSIC_DIRECTORY_PATH.mkdir(parents=True, exist_ok=True)
STREAM_SOURCE_MAX_AGE_SECONDS = 180
VOICE_STATE_SETTLE_SECONDS = 1.0
PCM_FRAME_DURATION_SECONDS = 0.02
PCM_FRAME_BYTES = 3840
PCM_BYTES_PER_SECOND = PCM_FRAME_BYTES / PCM_FRAME_DURATION_SECONDS
PCM_SILENCE_FRAME = b"\x00" * PCM_FRAME_BYTES


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


def _is_allowed_media_url(url: str) -> bool:
    """Restrict extractor URLs to explicitly trusted public media hosts."""
    if not _looks_like_url(url):
        return True
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or parsed.username or parsed.password:
        return False
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in MEDIA_ALLOWED_DOMAINS
    )


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
INFO_CACHE_MAX_ENTRIES = 256
_info_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()


def _info_cache_set(key: str, data: dict) -> None:
    _info_cache[key] = (time_module.monotonic(), data)
    _info_cache.move_to_end(key)
    while len(_info_cache) > INFO_CACHE_MAX_ENTRIES:
        _info_cache.popitem(last=False)


def _info_cache_get(key: str) -> Optional[dict]:
    cached = _info_cache.get(key)
    if not cached:
        return None
    if (time_module.monotonic() - cached[0]) >= INFO_CACHE_TTL_SECONDS:
        _info_cache.pop(key, None)
        return None
    _info_cache.move_to_end(key)
    return cached[1]


def _create_ytdl() -> youtube_dl.YoutubeDL:
    return youtube_dl.YoutubeDL(dict(YTDL_OPTIONS))


def _create_search_ytdl() -> youtube_dl.YoutubeDL:
    # Flat extraction lists search results without resolving each entry's
    # formats (the slow part). For the search tool we only need
    # title/url/duration/uploader, so skip format processing entirely.
    opts = dict(YTDL_OPTIONS)
    opts["extract_flat"] = "in_playlist"
    opts.pop("format", None)
    return youtube_dl.YoutubeDL(opts)


def _extract_info_sync(
    url: str, *, download: bool, max_entries: Optional[int] = None
) -> dict:
    options = dict(YTDL_OPTIONS)
    if max_entries is not None:
        options["playlistend"] = max(1, max_entries)
    return youtube_dl.YoutubeDL(options).extract_info(url, download=download)


def _prepare_filename(entry: dict) -> str:
    return _create_ytdl().prepare_filename(entry)


async def _probe_info(
    url: str, *, loop: Optional[asyncio.AbstractEventLoop] = None
) -> dict:
    """Быстрое получение метаданных без скачивания, с кэшем."""
    loop = loop or asyncio.get_running_loop()
    cache_key = f"1:{url}"
    cached = _info_cache_get(cache_key)
    if cached is not None:
        return cached

    start = time_module.monotonic()
    data = await loop.run_in_executor(
        None, lambda: _extract_info_sync(url, download=False)
    )
    _info_cache_set(cache_key, data)
    logger.debug("yt_dlp probe took %.2fs for %s", time_module.monotonic() - start, url)
    return data


async def _probe_info_flat(
    url: str, *, loop: Optional[asyncio.AbstractEventLoop] = None
) -> dict:
    """Metadata-only search extraction (no per-entry formats), with cache."""
    loop = loop or asyncio.get_running_loop()
    cache_key = f"flat:{url}"
    cached = _info_cache_get(cache_key)
    if cached is not None:
        return cached

    start = time_module.monotonic()
    data = await loop.run_in_executor(
        None, lambda: _create_search_ytdl().extract_info(url, download=False)
    )
    _info_cache_set(cache_key, data)
    logger.debug(
        "yt_dlp flat probe took %.2fs for %s", time_module.monotonic() - start, url
    )
    return data


class _DeferredAudioSource(discord.AudioSource):
    """Metadata-only placeholder; it never starts an FFmpeg process."""

    def read(self) -> bytes:
        return b""


class _BufferedAudioSource(discord.AudioSource):
    """Read PCM ahead on a producer thread and absorb short network stalls."""

    def __init__(
        self,
        source: discord.AudioSource,
        *,
        label: str,
        max_buffer_seconds: float,
        start_buffer_seconds: float,
        start_timeout_seconds: float,
        underrun_grace_seconds: float,
        on_source_frame: Optional[Callable[[], None]] = None,
        on_played_frame: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        self.source = source
        self.label = label
        self.max_buffer_seconds = max_buffer_seconds
        self._start_timeout_seconds = start_timeout_seconds
        self._underrun_grace_seconds = underrun_grace_seconds
        max_frames = max(1, int(max_buffer_seconds / PCM_FRAME_DURATION_SECONDS))
        self._start_frames = min(
            max_frames,
            max(0, int(start_buffer_seconds / PCM_FRAME_DURATION_SECONDS)),
        )
        self._frames: queue_module.Queue[bytes] = queue_module.Queue(maxsize=max_frames)
        self._on_source_frame = on_source_frame
        self._on_played_frame = on_played_frame
        self._ready = threading.Event()
        self._source_ended = threading.Event()
        self._closed = threading.Event()
        self._playback_started = False
        self._cleanup_lock = threading.Lock()
        self._cleaned = False
        self._underrun_since: Optional[float] = None
        self.last_source_frame_monotonic = time_module.monotonic()
        self.underrun_count = 0
        if self._start_frames == 0:
            self._ready.set()
        self._producer = threading.Thread(
            target=self._produce,
            name="peacemusic-audio-buffer",
            daemon=True,
        )
        self._producer.start()

    @property
    def source_ended(self) -> bool:
        return self._source_ended.is_set()

    @property
    def volume(self) -> float:
        return float(getattr(self.source, "volume", 1.0))

    @volume.setter
    def volume(self, value: float) -> None:
        if hasattr(self.source, "volume"):
            self.source.volume = value

    @property
    def buffered_seconds(self) -> float:
        return self._frames.qsize() * PCM_FRAME_DURATION_SECONDS

    def _produce(self) -> None:
        try:
            while not self._closed.is_set():
                data = self.source.read()
                if not data:
                    break
                self.last_source_frame_monotonic = time_module.monotonic()
                if self._on_source_frame is not None:
                    with contextlib.suppress(Exception):
                        self._on_source_frame()
                while not self._closed.is_set():
                    try:
                        self._frames.put(data, timeout=0.1)
                        break
                    except queue_module.Full:
                        continue
                if self._frames.qsize() >= self._start_frames:
                    self._ready.set()
        except Exception:
            if not self._closed.is_set():
                logger.exception("Audio buffer producer failed for %s", self.label)
        finally:
            self._source_ended.set()
            self._ready.set()

    def read(self) -> bytes:
        if not self._playback_started:
            self._ready.wait(timeout=self._start_timeout_seconds)
            self._playback_started = True
            logger.info(
                "Audio buffer ready for %s: %.2fs",
                self.label,
                self.buffered_seconds,
            )

        try:
            data = self._frames.get(timeout=PCM_FRAME_DURATION_SECONDS * 2)
        except queue_module.Empty:
            if self._source_ended.is_set() or self._closed.is_set():
                return b""
            now = time_module.monotonic()
            if self._underrun_since is None:
                self._underrun_since = now
                self.underrun_count += 1
                logger.warning("Audio buffer underrun for %s", self.label)
            if now - self._underrun_since <= self._underrun_grace_seconds:
                return PCM_SILENCE_FRAME
            logger.error(
                "Audio buffer underrun grace expired for %s after %.1fs",
                self.label,
                now - self._underrun_since,
            )
            return b""

        if self._underrun_since is not None:
            logger.info(
                "Audio buffer recovered for %s after %.2fs",
                self.label,
                time_module.monotonic() - self._underrun_since,
            )
            self._underrun_since = None
        if self._on_played_frame is not None:
            with contextlib.suppress(Exception):
                self._on_played_frame(data)
        return data

    def is_opus(self) -> bool:
        is_opus = getattr(self.source, "is_opus", None)
        return bool(is_opus()) if callable(is_opus) else False

    def cleanup(self) -> None:
        with self._cleanup_lock:
            if self._cleaned:
                return
            self._cleaned = True
            self._closed.set()
            self._ready.set()
            with contextlib.suppress(Exception):
                self.source.cleanup()
        if self._producer is not threading.current_thread():
            self._producer.join(timeout=1.0)


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
        defer_audio: bool = False,
        max_entries: Optional[int] = None,
        force_refresh: bool = False,
    ) -> list["YTDLSource"]:
        loop = loop or asyncio.get_running_loop()

        cache_key = f"{int(stream)}:{max_entries or 0}:{url}"
        use_cache = stream
        cached = _info_cache_get(cache_key) if use_cache and not force_refresh else None

        if cached is not None:
            data = cached
            logger.debug("yt_dlp extract_info cache hit for %s", url)
        else:
            start_time = time_module.monotonic()
            data = await loop.run_in_executor(
                None,
                lambda: _extract_info_sync(
                    url, download=not stream, max_entries=max_entries
                ),
            )
            elapsed = time_module.monotonic() - start_time
            if use_cache:
                _info_cache_set(cache_key, data)
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

            if defer_audio:
                audio_source = _DeferredAudioSource()
            else:
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
    source_prepared: bool = True


@dataclass(frozen=True)
class UserNotificationResult:
    text: str
    user_notified: bool = False


class _InteractionMessageAdapter:
    def __init__(self, interaction: discord.Interaction):
        self._interaction = interaction
        self.author = interaction.user
        self.channel = interaction.channel
        self.guild = interaction.guild
        self.id = getattr(interaction, "id", None)

    async def reply(
        self,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
    ) -> discord.Message:
        if not self._interaction.response.is_done():
            await self._interaction.response.send_message(content=content, embed=embed)
            return await self._interaction.original_response()
        return await self._interaction.followup.send(
            content=content,
            embed=embed,
            wait=True,
        )


# ----------------------------------------------------------------------------
# Music Cog
# ----------------------------------------------------------------------------


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot, *, _guild_id: Optional[int] = None):
        self.bot = bot
        self._guild_id = _guild_id
        self._guild_players: dict[int, Music] = {}
        self.voice_client: Optional[discord.VoiceClient] = None
        self.queue: Deque[QueuedTrack] = deque()
        self.current: Optional[QueuedTrack] = None
        self._play_lock = asyncio.Lock()
        self._last_audio_time: Optional[float] = None
        self._last_stream_input_time: Optional[float] = None
        self._track_start_monotonic: Optional[float] = None
        self._paused_at_monotonic: Optional[float] = None
        self._playback_base_seconds = 0.0
        self._played_audio_seconds = 0.0
        self._last_restart_attempt_monotonic: Optional[float] = None
        self._restart_lock = asyncio.Lock()
        self._suppressed_after_callbacks = 0
        self.loop_mode = "off"
        self._replay_track: Optional[QueuedTrack] = None
        self._volume = 1.0

        if self._guild_id is None:
            self.check_for_inactivity.start()
            self.monitor_stalled_playback.start()

    def cog_unload(self) -> None:
        self.check_for_inactivity.cancel()
        self.monitor_stalled_playback.cancel()
        for player in self._guild_players.values():
            player._cleanup_queue()
            source_owned_by_player = bool(
                player.voice_client
                and (
                    player.voice_client.is_playing() or player.voice_client.is_paused()
                )
            )
            player._cleanup_track_file(
                player.current,
                cleanup_source=not source_owned_by_player,
            )

    def _player_for_message(self, message: discord.Message) -> "Music":
        """Return isolated playback state for the message's guild."""
        if self._guild_id is not None:
            return self
        guild = getattr(message, "guild", None)
        if guild is None:
            return self
        player = self._guild_players.get(guild.id)
        if player is None:
            player = Music(self.bot, _guild_id=guild.id)
            self._guild_players[guild.id] = player
        return player

    async def _control_denied(
        self, message: discord.Message
    ) -> Optional[UserNotificationResult]:
        """Only listeners in the bot's channel (or guild managers) control it."""
        if not self.voice_client or not self.voice_client.is_connected():
            return None
        author = message.author
        permissions = getattr(author, "guild_permissions", None)
        if bool(getattr(permissions, "manage_guild", False)):
            return None
        author_channel = getattr(getattr(author, "voice", None), "channel", None)
        if author_channel == self.voice_client.channel:
            return None
        notified = await self._safe_reply(
            message,
            content="Для управления зайди в тот же голосовой канал, что и бот.",
        )
        return self._result("Нет доступа к плееру", user_notified=notified)

    async def disconnect_all(self) -> None:
        for player in list(self._guild_players.values()):
            async with player._play_lock:
                source_owned_by_player = bool(
                    player.voice_client
                    and (
                        player.voice_client.is_playing()
                        or player.voice_client.is_paused()
                    )
                )
                if player.voice_client is not None:
                    with contextlib.suppress(Exception):
                        await player.voice_client.disconnect(force=True)
                player.voice_client = None
                player._cleanup_queue()
                player._cleanup_track_file(
                    player.current,
                    cleanup_source=not source_owned_by_player,
                )
                player.current = None

    def _cleanup_track_file(
        self,
        track: Optional[QueuedTrack],
        *,
        cleanup_source: bool = True,
    ) -> None:
        if not track:
            return
        if cleanup_source:
            with contextlib.suppress(Exception):
                track.source.cleanup()
        if not track.local_path:
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

    def _discard_prepared_track(
        self,
        prepared_track: QueuedTrack,
        original_track: QueuedTrack,
    ) -> None:
        """Clean resources created while preparing a stale state transition."""
        if prepared_track.source is not original_track.source:
            with contextlib.suppress(Exception):
                prepared_track.source.cleanup()
        if (
            prepared_track.local_path
            and prepared_track.local_path != original_track.local_path
        ):
            with contextlib.suppress(FileNotFoundError, OSError):
                prepared_track.local_path.unlink()

    def _result(
        self, text: str, *, user_notified: bool = False
    ) -> UserNotificationResult:
        return UserNotificationResult(text=text, user_notified=user_notified)

    async def _run_slash_command(
        self,
        interaction: discord.Interaction,
        *,
        tool_name: str,
        handler,
        **tool_args: object,
    ) -> None:
        message = _InteractionMessageAdapter(interaction)
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        try:
            result = await handler(message, **tool_args)
        except Exception:
            logger.exception("Slash command %s failed", tool_name)
            await message.reply(content="Не удалось выполнить музыкальную команду.")
            chat_cog = self.bot.get_cog("GeminiChatCog")
            if chat_cog is not None and interaction.channel_id is not None:
                try:
                    await chat_cog.persist_manual_music_command(
                        channel_id=interaction.channel_id,
                        tool_name=tool_name,
                        args=tool_args,
                        response={"error": "Music command failed internally."},
                        user_notified=True,
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist manual music error %s for channel %s",
                        tool_name,
                        interaction.channel_id,
                    )
            return

        user_notified = result.user_notified
        if not user_notified:
            await message.reply(content=self._truncate_message_content(result.text))
            user_notified = True

        chat_cog = self.bot.get_cog("GeminiChatCog")
        if chat_cog is not None and interaction.channel_id is not None:
            try:
                await chat_cog.persist_manual_music_command(
                    channel_id=interaction.channel_id,
                    tool_name=tool_name,
                    args=tool_args,
                    response={"result": result.text},
                    user_notified=user_notified,
                )
            except Exception:
                logger.exception(
                    "Failed to persist manual music command %s for channel %s",
                    tool_name,
                    interaction.channel_id,
                )

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
            await channel.send(
                content=self._truncate_message_content(content), embed=embed
            )
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
            logger.warning(
                "Failed to reply to message %s",
                getattr(message, "id", None),
                exc_info=True,
            )
            return await self._safe_channel_send(
                message.channel, content=payload, embed=embed
            )

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
            await target.edit(
                content=self._truncate_message_content(content), embed=embed
            )
            return True
        except discord.HTTPException:
            logger.warning(
                "Failed to edit message %s", getattr(target, "id", None), exc_info=True
            )
            return False

    async def _safe_delete_message(self, target: Optional[discord.Message]) -> bool:
        if target is None:
            return False
        try:
            await target.delete()
            return True
        except discord.HTTPException:
            logger.warning(
                "Failed to delete message %s",
                getattr(target, "id", None),
                exc_info=True,
            )
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

    def _touch_stream_input_heartbeat(self) -> None:
        self._last_stream_input_time = time_module.monotonic()

    def _record_played_audio_frame(self, data: bytes) -> None:
        self._played_audio_seconds += len(data) / PCM_BYTES_PER_SECOND
        self._touch_audio_heartbeat()

    def _reset_playback_timers(self) -> None:
        self._track_start_monotonic = None
        self._paused_at_monotonic = None
        self._playback_base_seconds = 0.0
        self._played_audio_seconds = 0.0
        self._last_stream_input_time = None
        self._last_restart_attempt_monotonic = None

    def _mark_playback_started(self, *, start_at: int = 0) -> None:
        now = time_module.monotonic()
        self._track_start_monotonic = now
        self._paused_at_monotonic = None
        self._playback_base_seconds = float(max(start_at, 0))
        self._played_audio_seconds = 0.0
        self._last_stream_input_time = now
        self._touch_audio_heartbeat()

    def _current_progress_seconds(self) -> int:
        return max(
            0,
            int(self._playback_base_seconds + self._played_audio_seconds),
        )

    def _suppress_after_callback_once(self) -> None:
        self._suppressed_after_callbacks += 1

    def _stop_voice_client_for_replace(self) -> None:
        if self.voice_client and (
            self.voice_client.is_playing() or self.voice_client.is_paused()
        ):
            self._suppress_after_callback_once()
            self.voice_client.stop()

    def _restart_cooldown_active(self, now: Optional[float] = None) -> bool:
        if self._last_restart_attempt_monotonic is None:
            return False
        current_time = now if now is not None else time_module.monotonic()
        return (
            current_time - self._last_restart_attempt_monotonic
            < MUSIC_STREAM_RESTART_COOLDOWN_SECONDS
        )

    def _create_local_track_source(
        self,
        file_path: Path,
        *,
        seek: Optional[int] = None,
        on_chunk: Optional[Callable[[], None]] = None,
    ) -> discord.AudioSource:
        ffmpeg_args = build_ffmpeg_options(stream=False, seek=seek)
        audio_source = discord.FFmpegPCMAudio(str(file_path), **ffmpeg_args)
        transformer = discord.PCMVolumeTransformer(audio_source, volume=self._volume)
        original_read = transformer.read

        def _read_with_heartbeat() -> bytes:
            data = original_read()
            if data:
                self._record_played_audio_frame(data)
                if on_chunk is not None:
                    with contextlib.suppress(Exception):
                        on_chunk()
            return data

        transformer.read = _read_with_heartbeat  # type: ignore[assignment]
        return transformer

    def _create_stream_track_source(
        self,
        track: QueuedTrack,
        *,
        seek: Optional[int] = None,
    ) -> discord.AudioSource:
        if not track.stream_url:
            raise ValueError("Stream URL is required to create an audio source")
        ffmpeg_args = build_ffmpeg_options(
            stream=True,
            seek=seek,
            user_agent=track.user_agent,
            youtube_hls=track.is_youtube_hls,
        )
        audio_source = discord.FFmpegPCMAudio(track.stream_url, **ffmpeg_args)
        transformer = discord.PCMVolumeTransformer(audio_source, volume=self._volume)
        return _BufferedAudioSource(
            transformer,
            label=track.title,
            max_buffer_seconds=MUSIC_STREAM_BUFFER_SECONDS,
            start_buffer_seconds=MUSIC_STREAM_START_BUFFER_SECONDS,
            start_timeout_seconds=MUSIC_STREAM_START_TIMEOUT_SECONDS,
            underrun_grace_seconds=MUSIC_STREAM_UNDERRUN_GRACE_SECONDS,
            on_source_frame=self._touch_stream_input_heartbeat,
            on_played_frame=self._record_played_audio_frame,
        )

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
            source_prepared=not isinstance(src.original, _DeferredAudioSource),
        )

    # ------------------------------------------------------------------
    # Queue helpers
    # ------------------------------------------------------------------
    async def _ensure_voice_client(
        self, message: discord.Message
    ) -> Optional[discord.VoiceClient]:
        author = message.author
        if (
            not isinstance(author, discord.Member)
            or not author.voice
            or not author.voice.channel
        ):
            return None

        guild = getattr(message, "guild", None)
        current_vc = guild.voice_client if guild else self.voice_client

        if current_vc:
            if current_vc.is_connected():
                if current_vc.channel != author.voice.channel:
                    await current_vc.move_to(author.voice.channel)
            else:
                try:
                    await current_vc.disconnect(force=True)
                except Exception:
                    pass
                current_vc = await author.voice.channel.connect(timeout=15)
        else:
            current_vc = await author.voice.channel.connect(timeout=15)

        self.voice_client = current_vc
        return self.voice_client

    async def _refresh_track_source(
        self,
        track: QueuedTrack,
        *,
        seek: Optional[int] = None,
        force_extract: bool = False,
        cleanup_existing: bool = True,
        follow_playback_progress: bool = False,
    ) -> bool:
        seek_seconds = max(0, seek or 0)

        if track.local_path and track.local_path.exists():
            old_source = track.source
            new_source = self._create_local_track_source(
                track.local_path,
                seek=seek_seconds or None,
                on_chunk=self._touch_audio_heartbeat,
            )
            track.source = new_source
            if cleanup_existing:
                with contextlib.suppress(Exception):
                    old_source.cleanup()
            if not track.should_stream:
                track.stream_url = None
                track.user_agent = None
            track.prepared_at_monotonic = time_module.monotonic()
            track.source_prepared = True
            return True

        stream_url_is_fresh = (
            track.should_stream
            and track.stream_url is not None
            and (time_module.monotonic() - track.prepared_at_monotonic)
            <= STREAM_SOURCE_MAX_AGE_SECONDS
        )
        if stream_url_is_fresh and not force_extract:
            old_source = track.source
            new_source = self._create_stream_track_source(
                track,
                seek=seek_seconds or None,
            )
            track.source = new_source
            if cleanup_existing:
                with contextlib.suppress(Exception):
                    old_source.cleanup()
            track.source_prepared = True
            return True

        target_query = track.reload_query or track.webpage_url or track.stream_url
        if not target_query:
            return False

        sources = await YTDLSource.from_url(
            target_query,
            loop=self.bot.loop,
            stream=track.should_stream,
            start_at=seek_seconds or None,
            volume=self._volume,
            defer_audio=True,
            force_refresh=True,
        )
        if not sources:
            return False

        metadata_source = sources[0]
        old_source = track.source
        old_local_path = track.local_path
        track.title = metadata_source.title or track.title
        track.stream_url = metadata_source.url if metadata_source.is_stream else None
        track.webpage_url = metadata_source.webpage_url or track.webpage_url
        track.thumbnail = metadata_source.thumbnail or track.thumbnail
        track.uploader = metadata_source.uploader or track.uploader
        track.duration = metadata_source.duration or track.duration
        track.local_path = metadata_source.local_path
        track.is_youtube_hls = metadata_source.is_youtube_hls
        track.user_agent = metadata_source.user_agent
        if follow_playback_progress:
            seek_seconds = max(0, self._current_progress_seconds() - 2)
        if track.should_stream:
            prepared_source = self._create_stream_track_source(
                track,
                seek=seek_seconds or None,
            )
        elif track.local_path:
            prepared_source = self._create_local_track_source(
                track.local_path,
                seek=seek_seconds or None,
                on_chunk=self._touch_audio_heartbeat,
            )
        else:
            return False
        track.source = prepared_source
        if cleanup_existing:
            with contextlib.suppress(Exception):
                old_source.cleanup()
        track.prepared_at_monotonic = time_module.monotonic()
        track.source_prepared = True

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
        needs_refresh = not track.source_prepared or start_at > 0 or force_refresh
        if (
            track.should_stream
            and track.reload_query
            and (time_module.monotonic() - track.prepared_at_monotonic)
            > STREAM_SOURCE_MAX_AGE_SECONDS
        ):
            needs_refresh = True

        if needs_refresh:
            refreshed = await self._refresh_track_source(
                track,
                seek=start_at or None,
                force_extract=force_refresh,
            )
            if not refreshed:
                return False

        self.current = track
        try:
            self.voice_client.play(track.source, after=self._after_playback)
        except Exception:
            if track.should_stream and track.reload_query and not needs_refresh:
                logger.warning(
                    "Retrying playback with a refreshed stream for %s", track.title
                )
                refreshed = await self._refresh_track_source(
                    track,
                    seek=start_at or None,
                    force_extract=True,
                )
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
                logger.warning(
                    "Failed to prepare playback for %s: %s", track.title, exc
                )
                played = False
            except Exception:
                logger.exception("Unexpected playback setup error for %s", track.title)
                played = False

            if played:
                return

            self._cleanup_track_file(track)

    async def _skip_current_track(self) -> Optional[str]:
        if not self.voice_client or (
            not self.voice_client.is_playing() and not self.voice_client.is_paused()
        ):
            return None
        skipped_track = self.current
        skipped_title = skipped_track.title if skipped_track else "текущий трек"
        self.current = None
        self._replay_track = None
        self._reset_playback_timers()
        self._suppress_after_callback_once()
        self.voice_client.stop()
        # AudioPlayer owns the active source and cleans it in its thread's
        # finalizer. Cleaning it here can race with one last read().
        self._cleanup_track_file(skipped_track, cleanup_source=False)
        await self._start_next_track()
        return skipped_title

    def _after_playback(self, error: Optional[Exception]) -> None:
        asyncio.run_coroutine_threadsafe(
            self._handle_after_playback(error), self.bot.loop
        )

    async def _handle_after_playback(self, error: Optional[Exception]) -> None:
        async with self._play_lock:
            await self._handle_after_playback_locked(error)

    async def _handle_after_playback_locked(self, error: Optional[Exception]) -> None:
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
                await self._requeue_and_continue(finished_track)
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
        await self._start_next_track()

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
                    source=_DeferredAudioSource(),
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
                    source_prepared=False,
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
                defer_audio=True,
                max_entries=MUSIC_QUEUE_MAX_SIZE - len(self.queue),
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
        async with self._restart_lock:
            async with self._play_lock:
                voice_client = self.voice_client
                current_track = self.current
                if (
                    not voice_client
                    or not current_track
                    or not current_track.should_stream
                    or current_track.local_path
                ):
                    return
                now = time_module.monotonic()
                if self._restart_cooldown_active(now):
                    return
                self._last_restart_attempt_monotonic = now
                target_url = (
                    current_track.reload_query
                    or current_track.webpage_url
                    or current_track.stream_url
                )
                if not target_url:
                    return
                seek_seconds = max(0, self._current_progress_seconds() - 2)
                prepared_track = replace(current_track)

            logger.warning(
                "Playback stalled, attempting to restart stream for %s", target_url
            )
            try:
                refreshed = await self._refresh_track_source(
                    prepared_track,
                    seek=seek_seconds,
                    force_extract=True,
                    cleanup_existing=False,
                    follow_playback_progress=True,
                )
            except DownloadError as exc:
                self._discard_prepared_track(prepared_track, current_track)
                logger.warning("Failed to restart stream %s: %s", target_url, exc)
                return
            except Exception:
                self._discard_prepared_track(prepared_track, current_track)
                logger.exception(
                    "Unexpected error during stream restart for %s", target_url
                )
                return

            if not refreshed:
                self._discard_prepared_track(prepared_track, current_track)
                return
            seek_seconds = max(0, self._current_progress_seconds() - 2)

            async with self._play_lock:
                if (
                    current_track is not self.current
                    or voice_client is not self.voice_client
                    or not voice_client.is_connected()
                    or (not voice_client.is_playing() and not voice_client.is_paused())
                ):
                    self._discard_prepared_track(prepared_track, current_track)
                    return

                self._stop_voice_client_for_replace()
                self.current = prepared_track
                try:
                    voice_client.play(
                        prepared_track.source,
                        after=self._after_playback,
                    )
                except Exception:
                    self.current = None
                    self._reset_playback_timers()
                    self._discard_prepared_track(prepared_track, current_track)
                    logger.exception(
                        "Failed to restart playback for %s", current_track.title
                    )
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
    async def search_func(
        self, message: discord.Message, query: str
    ) -> UserNotificationResult:
        normalized = normalize_audio_query(query)
        if not _looks_like_url(normalized) and not normalized.startswith(
            ("ytsearch", "scsearch")
        ):
            search_query = f"ytsearch5:{normalized}"
        else:
            search_query = normalized

        try:
            data = await _probe_info_flat(search_query)
        except Exception as exc:  # noqa: BLE001
            return self._result(f"Ошибка поиска: {exc}", user_notified=False)

        entries = data.get("entries") or ([data] if data.get("title") else [])
        lines: list[str] = []
        for entry in entries[:5]:
            if not entry:
                continue
            title = entry.get("title", "Unknown")
            duration = format_duration(entry.get("duration"))
            uploader = entry.get("uploader") or entry.get("channel") or "Unknown"
            url = entry.get("webpage_url") or entry.get("url", "")
            lines.append(f"{len(lines) + 1}. {title} ({duration}) — {uploader} | {url}")

        if not lines:
            return self._result("Ничего не найдено.", user_notified=False)

        summary = (
            f"Найдено {len(lines)} результатов по запросу «{query}»:\n"
            + "\n".join(lines)
        )
        return self._result(summary, user_notified=False)

    async def play_func(
        self, message: discord.Message, song_name: str
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.play_func(message, song_name)
        denied = await self._control_denied(message)
        if denied:
            return denied
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

            if len(self.queue) >= MUSIC_QUEUE_MAX_SIZE:
                return self._result(
                    f"Очередь заполнена ({MUSIC_QUEUE_MAX_SIZE} треков максимум). "
                    "Пропустите или удалите несколько треков перед добавлением.",
                    user_notified=False,
                )

            tracks: list[QueuedTrack]
            normalized_query = normalize_audio_query(song_name)
            if normalized_query != song_name:
                logger.debug(
                    "Normalized audio query from %s to %s", song_name, normalized_query
                )

            if not _is_allowed_media_url(normalized_query):
                notified = await self._safe_reply(
                    message,
                    content="Этот домен не разрешён для загрузки медиа.",
                )
                return self._result(
                    "Домен источника не разрешён", user_notified=notified
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
                    defer_audio=True,
                    max_entries=MUSIC_QUEUE_MAX_SIZE - len(self.queue),
                )
            except DownloadError as exc:
                logger.warning("Failed to download track %s: %s", normalized_query, exc)
                notified = await self._safe_edit_message(
                    msg, content="Источник не смог обработать этот запрос."
                )
                if not notified:
                    notified = await self._safe_reply(
                        message, content="Источник не смог обработать этот запрос."
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

            remaining_slots = MUSIC_QUEUE_MAX_SIZE - len(self.queue)
            tracks = tracks[:remaining_slots]

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
                user_notified = await self._safe_edit_message(
                    msg, content=None, embed=embed
                )
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
        player = self._player_for_message(message)
        if player is not self:
            return await player.play_attachment_func(message, attachment)
        denied = await self._control_denied(message)
        if denied:
            return denied
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

            attachment_size = int(getattr(attachment, "size", 0) or 0)
            if attachment_size > MUSIC_ATTACHMENT_MAX_BYTES:
                notified = await self._safe_reply(
                    message,
                    content=(
                        "Аудиофайл слишком большой. Максимальный размер: "
                        f"{MUSIC_ATTACHMENT_MAX_BYTES // 1_000_000} МБ."
                    ),
                )
                return self._result("Аудиофайл слишком большой", user_notified=notified)

            if len(self.queue) >= MUSIC_QUEUE_MAX_SIZE:
                return self._result(
                    f"Очередь заполнена ({MUSIC_QUEUE_MAX_SIZE} треков максимум)."
                )

            # Save file with unique name
            safe_filename = Path(attachment.filename).name
            file_path = (
                MUSIC_DIRECTORY_PATH / f"{time_module.time_ns()}_{safe_filename}"
            )

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

            if file_path.stat().st_size > MUSIC_ATTACHMENT_MAX_BYTES:
                with contextlib.suppress(OSError):
                    file_path.unlink()
                notified = await self._safe_reply(
                    message, content="Аудиофайл превышает допустимый размер."
                )
                return self._result(
                    "Аудиофайл слишком большой",
                    user_notified=notified,
                )

            track = QueuedTrack(
                source=_DeferredAudioSource(),
                title=safe_filename,
                requester=message.author,
                local_path=file_path,
                webpage_url=attachment.url,
                channel=message.channel,
                should_stream=False,
                source_prepared=False,
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
        player = self._player_for_message(message)
        if player is not self:
            return await player.skip_func(message)
        denied = await self._control_denied(message)
        if denied:
            return denied
        async with self._play_lock:
            skipped = await self._skip_current_track()
        if skipped is None:
            notified = await self._safe_reply(
                message, content="Сейчас ничего не играет."
            )
            return self._result("Очередь не воспроизводится", user_notified=notified)
        notified = await self._safe_reply(message, content=f"Пропускаю: {skipped}")
        return self._result(f"Пропущен трек: {skipped}", user_notified=notified)

    async def skip_by_name_func(
        self, message: discord.Message, song_name: str
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.skip_by_name_func(message, song_name)
        denied = await self._control_denied(message)
        if denied:
            return denied
        lowercase_query = song_name.lower()
        skipped_title: Optional[str] = None
        removed_track: Optional[QueuedTrack] = None
        async with self._play_lock:
            if self.current and lowercase_query in self.current.title.lower():
                skipped_title = await self._skip_current_track()
            else:
                for track in list(self.queue):
                    if lowercase_query in track.title.lower():
                        self.queue.remove(track)
                        self._cleanup_track_file(track)
                        removed_track = track
                        break

        if skipped_title is not None:
            notified = await self._safe_reply(
                message, content=f"Пропущен текущий трек: {skipped_title}"
            )
            return self._result(
                f"Пропущен текущий трек: {skipped_title}",
                user_notified=notified,
            )
        if removed_track is not None:
            notified = await self._safe_reply(
                message, content=f"Удалено из очереди: {removed_track.title}"
            )
            return self._result(
                f"Удалено из очереди: {removed_track.title}",
                user_notified=notified,
            )
        notified = await self._safe_reply(
            message, content="Такой трек не найден в очереди."
        )
        return self._result("Трек не найден", user_notified=notified)

    async def stop_func(self, message: discord.Message) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.stop_func(message)
        denied = await self._control_denied(message)
        if denied:
            return denied
        async with self._play_lock:
            self.loop_mode = "off"
            self._replay_track = None
            self._cleanup_queue()
            current_track = self.current
            self.current = None
            self._reset_playback_timers()
            source_owned_by_player = bool(
                self.voice_client
                and (self.voice_client.is_playing() or self.voice_client.is_paused())
            )
            if source_owned_by_player:
                self._suppress_after_callback_once()
                self.voice_client.stop()
            self._cleanup_track_file(
                current_track,
                cleanup_source=not source_owned_by_player,
            )
        notified = await self._safe_reply(
            message, content="Очередь очищена и воспроизведение остановлено."
        )
        return self._result("Очередь очищена", user_notified=notified)

    async def summon_func(self, message: discord.Message) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.summon_func(message)
        denied = await self._control_denied(message)
        if denied:
            return denied
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
        notified = await self._safe_reply(message, content="Я уже с вами в канале!")
        return self._result("Бот в голосовом канале", user_notified=notified)

    async def disconnect_func(self, message: discord.Message) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.disconnect_func(message)
        denied = await self._control_denied(message)
        if denied:
            return denied
        async with self._play_lock:
            self.loop_mode = "off"
            self._replay_track = None
            current_track = self.current
            self.current = None
            self._reset_playback_timers()
            self._cleanup_queue()
            source_owned_by_player = bool(
                self.voice_client
                and (self.voice_client.is_playing() or self.voice_client.is_paused())
            )
            if self.voice_client:
                if source_owned_by_player:
                    self._suppress_after_callback_once()
                    self.voice_client.stop()
                await self.voice_client.disconnect(force=True)
                self.voice_client = None
            self._cleanup_track_file(
                current_track,
                cleanup_source=not source_owned_by_player,
            )
        notified = await self._safe_reply(
            message, content="Отключилась от канала и очистила очередь."
        )
        return self._result("Бот отключён", user_notified=notified)

    async def seek_func(
        self, message: discord.Message, time: str
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.seek_func(message, time)
        denied = await self._control_denied(message)
        if denied:
            return denied
        try:
            seconds = parse_time(time)
        except ValueError:
            notified = await self._safe_reply(
                message, content="Неверный формат времени. Пример: 1:23 или 73"
            )
            return self._result("Некорректное время", user_notified=notified)

        unavailable = False
        async with self._play_lock:
            voice_client = self.voice_client
            current_track = self.current
            if (
                not voice_client
                or not current_track
                or (not voice_client.is_playing() and not voice_client.is_paused())
            ):
                current_track = None
            elif not current_track.stream_url and not current_track.local_path:
                unavailable = True
            else:
                prepared_track = replace(current_track)

        if current_track is None:
            notified = await self._safe_reply(
                message, content="Сейчас ничего не играет."
            )
            return self._result("Нет трека для перемотки", user_notified=notified)
        if unavailable:
            notified = await self._safe_reply(
                message, content="Для этого трека перемотка недоступна."
            )
            return self._result("Перемотка недоступна", user_notified=notified)

        try:
            refreshed = await self._refresh_track_source(
                prepared_track,
                seek=seconds,
                cleanup_existing=False,
            )
        except DownloadError as exc:
            self._discard_prepared_track(prepared_track, current_track)
            logger.warning("Failed to seek %s: %s", current_track.title, exc)
            notified = await self._safe_reply(
                message, content="Не удалось перемотать трек."
            )
            return self._result("Ошибка перемотки", user_notified=notified)
        except Exception:
            self._discard_prepared_track(prepared_track, current_track)
            logger.exception("Unexpected seek error for %s", current_track.title)
            notified = await self._safe_reply(
                message, content="Не удалось перемотать трек."
            )
            return self._result("Ошибка перемотки", user_notified=notified)

        if not refreshed:
            self._discard_prepared_track(prepared_track, current_track)
            notified = await self._safe_reply(
                message, content="Для этого трека перемотка недоступна."
            )
            return self._result("Перемотка недоступна", user_notified=notified)

        stale_transition = False
        playback_failed = False
        async with self._play_lock:
            if (
                current_track is not self.current
                or voice_client is not self.voice_client
                or not voice_client.is_connected()
                or (not voice_client.is_playing() and not voice_client.is_paused())
            ):
                stale_transition = True
                self._discard_prepared_track(prepared_track, current_track)
            else:
                was_paused = voice_client.is_paused()
                self._stop_voice_client_for_replace()
                self.current = prepared_track
                try:
                    voice_client.play(
                        prepared_track.source,
                        after=self._after_playback,
                    )
                except Exception:
                    playback_failed = True
                    self.current = None
                    self._reset_playback_timers()
                    self._discard_prepared_track(prepared_track, current_track)
                    logger.exception(
                        "Failed to resume playback after seek for %s",
                        current_track.title,
                    )
                else:
                    self._mark_playback_started(start_at=seconds)
                    if was_paused:
                        voice_client.pause()
                        self._paused_at_monotonic = time_module.monotonic()

        if stale_transition:
            notified = await self._safe_reply(
                message, content="Трек изменился до завершения перемотки."
            )
            return self._result("Трек изменился", user_notified=notified)
        if playback_failed:
            notified = await self._safe_reply(
                message, content="Не удалось перемотать трек."
            )
            return self._result("Ошибка перемотки", user_notified=notified)
        notified = await self._safe_reply(
            message, content=f"Перемотала на {format_duration(seconds)}"
        )
        return self._result(
            f"Перемотала на {format_duration(seconds)}",
            user_notified=notified,
        )

    async def pause_func(self, message: discord.Message) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.pause_func(message)
        denied = await self._control_denied(message)
        if denied:
            return denied
        async with self._play_lock:
            paused = bool(self.voice_client and self.voice_client.is_playing())
            if paused:
                self.voice_client.pause()
                self._paused_at_monotonic = time_module.monotonic()
        if paused:
            notified = await self._safe_reply(
                message, content="Воспроизведение приостановлено."
            )
            return self._result("Воспроизведение на паузе", user_notified=notified)
        return self._result("Ничего не играет")

    async def resume_func(self, message: discord.Message) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.resume_func(message)
        denied = await self._control_denied(message)
        if denied:
            return denied
        async with self._play_lock:
            resumed = bool(self.voice_client and self.voice_client.is_paused())
            if resumed:
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
        if resumed:
            notified = await self._safe_reply(
                message, content="Воспроизведение продолжено."
            )
            return self._result("Воспроизведение продолжено", user_notified=notified)
        return self._result("Нечего продолжать")

    async def now_playing_func(
        self, message: discord.Message
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.now_playing_func(message)
        if (
            not self.voice_client
            or (
                not self.voice_client.is_playing() and not self.voice_client.is_paused()
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

    async def get_player_state_func(
        self, message: discord.Message
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.get_player_state_func(message)
        """One-shot snapshot of the whole player for situational awareness."""
        voice_client = self.voice_client
        connected = bool(voice_client and voice_client.is_connected())

        lines: list[str] = []
        if connected and voice_client.channel:
            lines.append(f"Голосовой канал: {voice_client.channel.name}")
        else:
            lines.append("Не подключена к голосовому каналу.")

        if self.current:
            paused = bool(voice_client and voice_client.is_paused())
            state = "на паузе" if paused else "играет"
            progress = format_duration(self._current_progress_seconds())
            duration = (
                format_duration(self.current.duration) if self.current.duration else "?"
            )
            lines.append(
                f"Сейчас {state}: {self.current.title} ({progress} / {duration})"
            )
            if self.current.uploader:
                lines.append(f"Автор: {self.current.uploader}")
        else:
            lines.append("Сейчас ничего не играет.")

        lines.append(f"Громкость: {int(self._volume * 100)}%")
        loop_labels = {"off": "выключен", "track": "трек", "queue": "очередь"}
        lines.append(f"Повтор: {loop_labels.get(self.loop_mode, self.loop_mode)}")

        if self.queue:
            preview = "; ".join(
                f"{index}. {track.title}"
                for index, track in enumerate(list(self.queue)[:5], start=1)
            )
            extra = len(self.queue) - 5
            suffix = f" (+ ещё {extra})" if extra > 0 else ""
            lines.append(f"В очереди {len(self.queue)}: {preview}{suffix}")
        else:
            lines.append("Очередь пуста.")

        return self._result("\n".join(lines), user_notified=False)

    async def who_is_listening_func(
        self, message: discord.Message
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.who_is_listening_func(message)
        """List the non-bot members currently in the bot's voice channel."""
        voice_client = self.voice_client
        if (
            not voice_client
            or not voice_client.is_connected()
            or not voice_client.channel
        ):
            return self._result("Бот не в голосовом канале.", user_notified=False)

        listeners = [
            member
            for member in voice_client.channel.members
            if not getattr(member, "bot", False)
        ]
        if not listeners:
            return self._result(
                "В голосовом канале нет слушателей (только бот).",
                user_notified=False,
            )

        names = ", ".join(member.display_name for member in listeners)
        return self._result(f"Слушают ({len(listeners)}): {names}", user_notified=False)

    async def get_queue_func(self, message: discord.Message) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.get_queue_func(message)
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
        player = self._player_for_message(message)
        if player is not self:
            return await player.shuffle_queue_func(message)
        denied = await self._control_denied(message)
        if denied:
            return denied
        async with self._play_lock:
            queue_empty = not self.queue
            if not queue_empty:
                queue_list = list(self.queue)
                random.shuffle(queue_list)
                self.queue.clear()
                self.queue.extend(queue_list)
        if queue_empty:
            return self._result("Очередь пуста, нечего перемешивать.")
        notified = await self._safe_reply(message, content="Очередь перемешана.")
        return self._result("Очередь перемешана", user_notified=notified)

    async def clear_queue_func(
        self, message: discord.Message
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.clear_queue_func(message)
        denied = await self._control_denied(message)
        if denied:
            return denied
        async with self._play_lock:
            queue_empty = not self.queue
            if not queue_empty:
                self._cleanup_queue()
                if self.loop_mode == "queue":
                    self.loop_mode = "off"
        if queue_empty:
            return self._result("Очередь и так пуста.")
        notified = await self._safe_reply(
            message, content="Очередь очищена (текущий трек продолжает играть)."
        )
        return self._result("Очередь очищена", user_notified=notified)

    async def remove_from_queue_func(
        self, message: discord.Message, index: int
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.remove_from_queue_func(message, index)
        denied = await self._control_denied(message)
        if denied:
            return denied
        removed_track: Optional[QueuedTrack] = None
        async with self._play_lock:
            queue_size = len(self.queue)
            if 1 <= index <= queue_size:
                removed_track = self.queue[index - 1]
                del self.queue[index - 1]
                self._cleanup_track_file(removed_track)
        if queue_size == 0:
            return self._result("Очередь пуста.")
        if removed_track is None:
            return self._result(f"Неверный индекс. В очереди {queue_size} треков.")
        notified = await self._safe_reply(
            message, content=f"Удалено из очереди: {removed_track.title}"
        )
        return self._result(
            f"Удален трек: {removed_track.title}", user_notified=notified
        )

    async def set_loop_mode_func(
        self, message: discord.Message, mode: str
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.set_loop_mode_func(message, mode)
        denied = await self._control_denied(message)
        if denied:
            return denied
        mode = mode.lower()
        if mode not in ("off", "track", "queue"):
            return self._result(
                "Неизвестный режим. Используйте 'off', 'track' или 'queue'."
            )

        async with self._play_lock:
            self.loop_mode = mode
        modes_tr = {"off": "Выключен", "track": "Текущий трек", "queue": "Вся очередь"}
        notified = await self._safe_reply(
            message, content=f"Режим повтора установлен на: {modes_tr[mode]}."
        )
        return self._result(f"Режим повтора: {mode}", user_notified=notified)

    async def set_volume_func(
        self, message: discord.Message, level: float
    ) -> UserNotificationResult:
        player = self._player_for_message(message)
        if player is not self:
            return await player.set_volume_func(message, level)
        denied = await self._control_denied(message)
        if denied:
            return denied
        if level < 0.0 or level > 5.0:
            notified = await self._safe_reply(
                message, content="Громкость должна быть в диапазоне 0.0-5.0."
            )
            return self._result(
                "Недопустимое значение громкости", user_notified=notified
            )

        async with self._play_lock:
            self._volume = level
            voice_client = self.voice_client
            source = getattr(voice_client, "source", None)
            if source is not None and hasattr(source, "volume"):
                source.volume = level
                active_source_updated = True
            else:
                active_source_updated = False
        if not voice_client:
            notified = await self._safe_reply(
                message,
                content=f"Громкость по умолчанию установлена на {int(level * 100)}%.",
            )
            return self._result(
                f"Громкость {int(level * 100)}%",
                user_notified=notified,
            )

        if active_source_updated:
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

    @app_commands.command(
        name="play", description="Добавить трек или плейлист в очередь."
    )
    @app_commands.describe(song_name="Название трека или ссылка.")
    async def play_slash(
        self, interaction: discord.Interaction, song_name: str
    ) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="play_music",
            handler=self.play_func,
            song_name=song_name,
        )

    @app_commands.command(name="skip", description="Пропустить текущий трек.")
    async def skip_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="skip_music",
            handler=self.skip_func,
        )

    @app_commands.command(
        name="stop", description="Остановить воспроизведение и очистить очередь."
    )
    async def stop_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="stop_music",
            handler=self.stop_func,
        )

    @app_commands.command(
        name="set_volume", description="Установить громкость от 0 до 5."
    )
    @app_commands.describe(level="Громкость, где 1.0 = 100%.")
    async def set_volume_slash(
        self, interaction: discord.Interaction, level: float
    ) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="set_volume",
            handler=self.set_volume_func,
            level=float(level),
        )

    @app_commands.command(
        name="skip_by_name", description="Удалить или пропустить трек по названию."
    )
    @app_commands.describe(song_name="Часть названия трека.")
    async def skip_by_name_slash(
        self, interaction: discord.Interaction, song_name: str
    ) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="skip_music_by_name",
            handler=self.skip_by_name_func,
            song_name=song_name,
        )

    @app_commands.command(name="seek", description="Перемотать текущий трек.")
    @app_commands.describe(time="Время в секундах, MM:SS или HH:MM:SS.")
    async def seek_slash(self, interaction: discord.Interaction, time: str) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="seek",
            handler=self.seek_func,
            time=time,
        )

    @app_commands.command(
        name="summon", description="Подключить бота к вашему голосовому каналу."
    )
    async def summon_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="summon",
            handler=self.summon_func,
        )

    @app_commands.command(
        name="disconnect", description="Отключить бота от голосового канала."
    )
    async def disconnect_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="disconnect",
            handler=self.disconnect_func,
        )

    @app_commands.command(
        name="pause", description="Поставить воспроизведение на паузу."
    )
    async def pause_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="pause_music",
            handler=self.pause_func,
        )

    @app_commands.command(name="resume", description="Продолжить воспроизведение.")
    async def resume_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="resume_music",
            handler=self.resume_func,
        )

    @app_commands.command(name="now_playing", description="Показать текущий трек.")
    async def now_playing_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="now_playing",
            handler=self.now_playing_func,
        )

    @app_commands.command(name="queue", description="Показать очередь треков.")
    async def queue_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="get_queue",
            handler=self.get_queue_func,
        )

    @app_commands.command(name="shuffle_queue", description="Перемешать очередь.")
    async def shuffle_queue_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="shuffle_queue",
            handler=self.shuffle_queue_func,
        )

    @app_commands.command(
        name="clear_queue", description="Очистить очередь, не трогая текущий трек."
    )
    async def clear_queue_slash(self, interaction: discord.Interaction) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="clear_queue",
            handler=self.clear_queue_func,
        )

    @app_commands.command(
        name="remove_from_queue", description="Удалить трек из очереди по номеру."
    )
    @app_commands.describe(index="Номер трека в очереди, начиная с 1.")
    async def remove_from_queue_slash(
        self, interaction: discord.Interaction, index: int
    ) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="remove_from_queue",
            handler=self.remove_from_queue_func,
            index=int(index),
        )

    @app_commands.command(name="loop_mode", description="Установить режим повтора.")
    @app_commands.describe(mode="off, track или queue.")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Выключен", value="off"),
            app_commands.Choice(name="Текущий трек", value="track"),
            app_commands.Choice(name="Вся очередь", value="queue"),
        ]
    )
    async def loop_mode_slash(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str]
    ) -> None:
        await self._run_slash_command(
            interaction,
            tool_name="loop_mode",
            handler=self.set_loop_mode_func,
            mode=mode.value,
        )

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------
    @tasks.loop(seconds=2)
    async def monitor_stalled_playback(self) -> None:
        for player in list(self._guild_players.values()):
            await player._monitor_stalled_playback_once()

    async def _monitor_stalled_playback_once(self) -> None:
        if not self.voice_client or not self.current:
            return
        if not self.voice_client.is_playing():
            return
        if self.current.local_path:
            return
        now = time_module.monotonic()
        if self._restart_cooldown_active(now):
            return
        source = self.current.source
        if isinstance(source, _BufferedAudioSource):
            if source.source_ended:
                if self.current.duration:
                    remaining = max(
                        0,
                        self.current.duration - self._current_progress_seconds(),
                    )
                    natural_eof_window = source.max_buffer_seconds + 5
                    if remaining <= natural_eof_window:
                        return
                logger.warning(
                    "Stream source ended early for %s at %ss; restarting",
                    self.current.title,
                    self._current_progress_seconds(),
                )
                await self._restart_current_stream()
                return
            last_input = source.last_source_frame_monotonic
        else:
            last_input = self._last_stream_input_time or self._last_audio_time or now
        if now - last_input > MUSIC_STREAM_STALL_TIMEOUT_SECONDS:
            logger.warning(
                "Stream input stalled for %.1fs on %s",
                now - last_input,
                self.current.title,
            )
            await self._restart_current_stream()

    @monitor_stalled_playback.before_loop
    async def before_monitor_stalled_playback(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def check_for_inactivity(self) -> None:
        for player in list(self._guild_players.values()):
            await player._check_for_inactivity_once()

    async def _check_for_inactivity_once(self) -> None:
        async with self._play_lock:
            now = time_module.monotonic()
            if self.voice_client and self.voice_client.is_connected():
                if (
                    not self.voice_client.is_playing()
                    and not self.voice_client.is_paused()
                ):
                    last_time = self._last_audio_time or now
                    if now - last_time > 1800:
                        await self.voice_client.disconnect(force=True)
                        self.voice_client = None
            if not self.voice_client or not self.voice_client.is_connected():
                if self.voice_client and (
                    self.voice_client.is_playing() or self.voice_client.is_paused()
                ):
                    # discord.py keeps AudioPlayer alive during a transient voice
                    # reconnect. Its source must remain valid until it resumes or
                    # the player thread exits by itself.
                    return
                self._cleanup_queue()
                self._cleanup_track_file(self.current)
                self.current = None
                self._replay_track = None
                self._reset_playback_timers()

    async def _handle_voice_disconnect_event(self, guild: discord.Guild) -> None:
        """Preserve playback while discord.py performs an automatic reconnect.

        A reconnect briefly emits a voice-state update with ``channel=None``.
        discord.py deliberately keeps the VoiceClient and AudioPlayer alive in
        that case, so cleaning the source here would race with AudioPlayer.read.
        """
        async with self._play_lock:
            voice_client = self.voice_client
        source_owned_by_player = False
        if voice_client is not None:
            # The protocol handler and Cog listener are dispatched as separate
            # tasks for the same gateway event. Give the protocol handler time
            # to either retain the cached client for reconnect or remove it for
            # a permanent disconnect.
            await asyncio.sleep(VOICE_STATE_SETTLE_SECONDS)
        async with self._play_lock:
            if self.voice_client is not voice_client:
                return
            if voice_client is not None and (
                voice_client.is_connected() or guild.voice_client is voice_client
            ):
                logger.info(
                    "Voice connection interrupted; preserving playback for reconnect"
                )
                return

            if voice_client is not None:
                source_owned_by_player = (
                    voice_client.is_playing() or voice_client.is_paused()
                )
                if source_owned_by_player:
                    self._suppress_after_callback_once()
                    voice_client.stop()

            current_track = self.current
            self.voice_client = None
            self._cleanup_queue()
            # If there was an AudioPlayer, its thread owns source cleanup. Avoid
            # invalidating FFmpeg stdout while that thread may still be reading.
            self._cleanup_track_file(
                current_track,
                cleanup_source=not source_owned_by_player,
            )
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
        player = self._guild_players.get(member.guild.id)
        if player is None:
            return
        if before.channel and after.channel is None:
            await player._handle_voice_disconnect_event(member.guild)
