
from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Optional
from urllib.parse import urlparse

import discord
import yt_dlp as youtube_dl
from discord.ext import commands, tasks
from yt_dlp.utils import DownloadError

from config import MUSIC_DIRECTORY

logger = logging.getLogger(__name__)

MUSIC_DIRECTORY_PATH = Path(MUSIC_DIRECTORY)
MUSIC_DIRECTORY_PATH.mkdir(parents=True, exist_ok=True)

COOKIES_PATH = Path(__file__).resolve().parent / "cookies.txt"


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
    parts = time_str.split(':')
    if len(parts) == 1:
        return int(parts[0])
    if len(parts) == 2:
        minutes, seconds = map(int, parts)
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError("Invalid time format. Use seconds, MM:SS, or HH:MM:SS.")


SOUNDCLOUD_DOMAINS = ("soundcloud.com", "on.soundcloud.com")
SOUNDCLOUD_QUERY_PREFIXES = ("sc ", "soundcloud ")
SOUNDCLOUD_QUERY_PREFIXES_WITH_COLON = ("sc:", "soundcloud:")


def _looks_like_url(query: str) -> bool:
    lowered = query.lower()
    return lowered.startswith(("http://", "https://"))


def normalize_audio_query(query: str) -> str:
    """Normalize user input to support explicit SoundCloud searches and URLs."""
    query = query.strip()
    if not query:
        return query

    lowered = query.lower()

    for prefix in SOUNDCLOUD_QUERY_PREFIXES:
        if lowered.startswith(prefix):
            rest = query[len(prefix):].strip()
            if rest:
                return f"scsearch1:{rest}"
            return query

    for prefix in SOUNDCLOUD_QUERY_PREFIXES_WITH_COLON:
        if lowered.startswith(prefix):
            rest = query[len(prefix):].strip()
            if rest:
                return f"scsearch1:{rest}"
            return query

    if lowered.startswith("scsearch"):
        return query

    if not _looks_like_url(query):
        stripped_query = query.lstrip("www.")
        if " " not in stripped_query and any(domain in stripped_query.lower() for domain in SOUNDCLOUD_DOMAINS):
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


YTDL_OPTIONS = {
    "cookiefile": str(COOKIES_PATH),            # оставляем, если нужно обходить ограничения/возраст/регион
    "format": "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio/best[acodec!=none]",
    "noplaylist": True,
    "nopart": True,
    "default_search": "ytsearch1",
    "outtmpl": str(MUSIC_DIRECTORY_PATH / "%(extractor)s-%(id)s.%(ext)s"),
    "http_chunk_size": 5_242_880,               # больше размер чанка — меньше перезапросов на длинных треках
    "forceipv4": True,

    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Referer": "https://www.youtube.com/",
        "Origin":  "https://www.youtube.com",
        "Accept-Language": "en-US,en;q=0.9"
    },

    # Не используем внешнего качальщика для YouTube/HLS
    # "external_downloader": "aria2c",  # отключено для YouTube

    # Для длинных HLS потоков лучше доверить ffmpeg, у него лучше переподключение
    "hls_prefer_native": False,

    "extractor_args": {
        "youtube": {
            "player_client": ["tv_embedded", "default"],
            "player_skip":   ["web_safari", "web"]
        }
    },

    "retries": 10,
    "fragment_retries": 15,
    "socket_timeout": 15,
    "verbose": True,
}


LOUDNESS_NORMALIZATION_FILTER = "loudnorm=I=-14:LRA=11:TP=-1.5"

FFMPEG_BEFORE_STREAM = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
    "-reconnect_at_eof 1 -reconnect_on_network_error 1 -reconnect_on_http_error 4xx,5xx "
    "-rw_timeout 15000000 -nostdin"
)
FFMPEG_BEFORE_FILE = "-nostdin"
FFMPEG_COMMON_OPTIONS = (
    "-vn -sn -dn "
    "-bufsize 256k "
    "-probesize 256k "
    "-flags low_delay "
    "-threads 1 "
    "-loglevel warning "
    f"-af {LOUDNESS_NORMALIZATION_FILTER}"
)

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _clean_progress_text(value: str) -> str:
    if not value:
        return ""
    cleaned = ANSI_ESCAPE_RE.sub("", value)
    return " ".join(cleaned.strip().split())


def build_ffmpeg_options(stream: bool, *, seek: Optional[int] = None) -> dict[str, str]:
    before = FFMPEG_BEFORE_STREAM if stream else FFMPEG_BEFORE_FILE
    if seek is not None and seek > 0:
        before = f"-ss {seek} {before}"
    return {
        "before_options": before,
        "options": FFMPEG_COMMON_OPTIONS,
    }

ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

INFO_CACHE_TTL_SECONDS = 900
_info_cache: dict[str, tuple[float, dict]] = {}
LONG_VIDEO_DOWNLOAD_THRESHOLD = 1800  # 30 минут: длинные ролики лучше скачать


async def _probe_info(url: str, *, loop: Optional[asyncio.AbstractEventLoop] = None) -> dict:
    """Быстрое получение метаданных без скачивания, с кэшем."""
    loop = loop or asyncio.get_event_loop()
    cache_key = f"probe:{url}"
    cached = _info_cache.get(cache_key)
    now = time.monotonic()
    if cached and (now - cached[0]) < INFO_CACHE_TTL_SECONDS:
        return cached[1]

    start = time.monotonic()
    data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
    _info_cache[cache_key] = (time.monotonic(), data)
    logger.debug("yt_dlp probe took %.2fs for %s", time.monotonic() - start, url)
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
        stream: bool = False,
        progress_hook: Optional[Callable[[dict], None]] = None,
        on_chunk: Optional[Callable[[], None]] = None,
        start_at: Optional[int] = None,
    ) -> list["YTDLSource"]:
        loop = loop or asyncio.get_event_loop()
        cache_key = f"{int(stream)}:{url}"
        cached = _info_cache.get(cache_key)
        now = time.monotonic()
        use_progress = bool(progress_hook) and not stream
        ytdl_client = ytdl if not use_progress else youtube_dl.YoutubeDL({**YTDL_OPTIONS, "progress_hooks": [progress_hook]})
        if cached and (now - cached[0]) < INFO_CACHE_TTL_SECONDS:
            data = cached[1]
            logger.debug("yt_dlp extract_info cache hit for %s", url)
        else:
            start_time = time.monotonic()
            data = await loop.run_in_executor(None, lambda: ytdl_client.extract_info(url, download=not stream))
            elapsed = time.monotonic() - start_time
            _info_cache[cache_key] = (time.monotonic(), data)
            logger.debug("yt_dlp extract_info took %.2fs for %s", elapsed, url)

        entries = data.get("entries", [data])

        sources: list[YTDLSource] = []
        for entry in entries:
            if not entry:
                continue
            local_path: Optional[Path] = None
            if stream:
                playback_target = entry["url"]
            else:
                filename = ytdl_client.prepare_filename(entry)
                local_path = Path(filename)
                playback_target = str(local_path)
            ffmpeg_args = build_ffmpeg_options(stream, seek=start_at)
            audio_source = discord.FFmpegPCMAudio(playback_target, **ffmpeg_args)
            sources.append(cls(audio_source, data=entry, stream=stream, local_path=local_path, on_chunk=on_chunk))
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
        self._last_audio_time: Optional[datetime.datetime] = None
        self._track_start_monotonic: Optional[float] = None
        self._restart_lock = asyncio.Lock()
        self._skip_after_callback = False

        self.check_for_inactivity.start()
        self.monitor_stalled_playback.start()

    async def _download_progress_worker(
        self,
        message: discord.Message,
        queue: asyncio.Queue[object],
        sentinel: object,
        *,
        update_interval: float = 0.5,
    ) -> None:
        last_content: Optional[str] = None
        last_update = 0.0

        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=update_interval)
            except asyncio.TimeoutError:
                continue

            if payload is sentinel:
                break

            if not isinstance(payload, dict):
                continue

            status = payload.get("status")
            now = time.monotonic()

            if status == "downloading" and (now - last_update) < update_interval:
                continue

            content = self._format_download_progress(payload)
            if not content or content == last_content:
                continue

            try:
                await message.edit(content=content, embed=None)
            except discord.HTTPException:
                return

            last_content = content
            last_update = now

            if status in {"finished", "error"}:
                break

    def _format_download_progress(self, payload: dict) -> str:
        status = payload.get("status")
        if status == "downloading":
            percent = _clean_progress_text(payload.get("_percent_str") or "")
            speed = _clean_progress_text(payload.get("_speed_str") or "")
            eta = _clean_progress_text(payload.get("_eta_str") or "")

            details: list[str] = []
            if percent:
                details.append(percent)
            if speed and speed.lower() != "nan":
                details.append(speed)
            if eta and eta.lower() != "n/a":
                details.append(f"ETA {eta}")

            details_text = " • ".join(details)
            return f"Загружаю трек… {details_text}" if details_text else "Загружаю трек…"

        if status == "finished":
            return "Загрузка завершена, подготавливаю аудио…"
        if status == "error":
            return "Ошибка при загрузке трека."
        return "Готовлю загрузку трека…"

    def _cleanup_track_file(self, track: Optional[QueuedTrack]) -> None:
        if not track or not track.local_path:
            return
        try:
            track.local_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Failed to delete downloaded track %s", track.local_path, exc_info=True)
        track.local_path = None

    def _cleanup_queue(self) -> None:
        for track in list(self.queue):
            self._cleanup_track_file(track)
        self.queue.clear()

    def _touch_audio_heartbeat(self) -> None:
        self._last_audio_time = discord.utils.utcnow()

    # ------------------------------------------------------------------
    # Queue helpers
    # ------------------------------------------------------------------
    async def _ensure_voice_client(self, message: discord.Message) -> Optional[discord.VoiceClient]:
        author = message.author
        if not author.voice or not author.voice.channel:
            await message.reply("Ты не подключен к голосовому каналу.")
            return None

        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel != author.voice.channel:
                await self.voice_client.move_to(author.voice.channel)
        else:
            self.voice_client = await author.voice.channel.connect(timeout=15)
        return self.voice_client

    async def _start_next_track(self) -> None:
        if not self.voice_client:
            return
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            return
        if not self.queue:
            self.current = None
            return

        self.current = self.queue.popleft()
        logger.info("Now playing: %s", self.current.title)
        self._track_start_monotonic = time.monotonic()
        self._last_audio_time = discord.utils.utcnow()
        self.voice_client.play(self.current.source, after=self._after_playback)

    def _after_playback(self, error: Optional[Exception]) -> None:
        if self._skip_after_callback:
            self._skip_after_callback = False
            return
        finished_track = self.current
        if error:
            logger.error("Playback error", exc_info=error)
        if finished_track:
            self._cleanup_track_file(finished_track)
        self.current = None
        self._track_start_monotonic = None
        self.bot.loop.call_soon_threadsafe(asyncio.create_task, self._start_next_track())

    async def _restart_current_stream(self) -> None:
        if not self.voice_client or not self.current or not self.current.stream_url:
            return
        if self.current.local_path:
            return  # локальный файл — пусть завершится штатно
        async with self._restart_lock:
            target_url = self.current.webpage_url or self.current.stream_url
            if not target_url:
                return
            seek_seconds: Optional[int] = None
            if self._track_start_monotonic:
                seek_seconds = max(0, int(time.monotonic() - self._track_start_monotonic) - 2)
            logger.warning("Playback stalled, attempting to restart stream for %s", target_url)
            try:
                sources = await YTDLSource.from_url(
                    target_url,
                    loop=self.bot.loop,
                    stream=True,
                    on_chunk=self._touch_audio_heartbeat,
                    start_at=seek_seconds,
                )
            except DownloadError as exc:
                logger.warning("Failed to restart stream %s: %s", target_url, exc)
                return
            except Exception:
                logger.exception("Unexpected error during stream restart for %s", target_url)
                return

            if not sources:
                return

            new_source = sources[0]
            self._skip_after_callback = True
            self.voice_client.stop()
            self.current.source = new_source
            self.current.stream_url = new_source.url
            self.current.duration = new_source.duration
            self._track_start_monotonic = time.monotonic()
            self._touch_audio_heartbeat()
            self.voice_client.play(self.current.source, after=self._after_playback)

    def _build_track_embed(self, track: QueuedTrack, *, color: discord.Color) -> discord.Embed:
        embed = discord.Embed(
            title=track.title,
            url=track.webpage_url or discord.Embed.Empty,
            description="Трек добавлен в очередь",
            color=color,
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        if track.requester:
            embed.set_author(name=track.requester.display_name, icon_url=track.requester.display_avatar.url)
        if track.uploader:
            embed.add_field(name="Автор", value=track.uploader, inline=True)
        if track.duration:
            embed.add_field(name="Длительность", value=format_duration(track.duration), inline=True)
        embed.set_footer(text="Приятного прослушивания!")
        return embed

    # ------------------------------------------------------------------
    # Public functions used by the AI cog
    async def play_func(self, message: discord.Message, song_name: str) -> str:
        async with self._play_lock:
            voice_client = await self._ensure_voice_client(message)
            if not voice_client:
                return "Пользователь не в голосовом канале"

            tracks: list[QueuedTrack]
            normalized_query = normalize_audio_query(song_name)
            should_stream = not is_soundcloud_query(normalized_query)
            if should_stream:
                try:
                    probe = await _probe_info(normalized_query, loop=self.bot.loop)
                    probe_entries = probe.get("entries", [probe])
                    longest_duration = max(
                        int(entry.get("duration") or 0) for entry in probe_entries if entry
                    ) if probe_entries else 0
                    has_live = any(entry and entry.get("is_live") for entry in probe_entries)
                    if not has_live and longest_duration >= LONG_VIDEO_DOWNLOAD_THRESHOLD:
                        should_stream = False  # длинные видео качаем заранее
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to probe track duration for %s", normalized_query, exc_info=exc)
            if normalized_query != song_name:
                logger.debug("Normalized audio query from %s to %s", song_name, normalized_query)

            progress_message: Optional[discord.Message] = None
            progress_queue: Optional[asyncio.Queue[object]] = None
            progress_task: Optional[asyncio.Task[None]] = None
            progress_hook_fn: Optional[Callable[[dict], None]] = None
            progress_sentinel: Optional[object] = None

            if not should_stream:
                progress_queue = asyncio.Queue()
                progress_sentinel = object()
                progress_message = await message.reply("Готовлю загрузку трека…")
                progress_task = asyncio.create_task(
                    self._download_progress_worker(progress_message, progress_queue, progress_sentinel)
                )

                def yt_progress_hook(payload: dict) -> None:
                    if not payload or not progress_queue:
                        return
                    self.bot.loop.call_soon_threadsafe(progress_queue.put_nowait, dict(payload))

                progress_hook_fn = yt_progress_hook

            try:
                sources = await YTDLSource.from_url(
                    normalized_query,
                    loop=self.bot.loop,
                    stream=should_stream,
                    progress_hook=progress_hook_fn,
                    on_chunk=self._touch_audio_heartbeat,
                )
            except DownloadError as exc:
                logger.warning("Failed to download track %s: %s", normalized_query, exc)
                if progress_queue and progress_sentinel is not None:
                    progress_queue.put_nowait(progress_sentinel)
                if progress_task:
                    with contextlib.suppress(asyncio.CancelledError):
                        await progress_task
                progress_queue = None
                progress_task = None
                progress_sentinel = None
                if progress_message:
                    with contextlib.suppress(discord.HTTPException):
                        await progress_message.edit(content="Не удалось загрузить трек.", embed=None)
                else:
                    await message.reply("Не удалось загрузить трек.")
                return "Ошибка загрузки"
            except Exception as exc:  # noqa: BLE001 - логируем и уведомляем пользователя
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.exception("Unexpected error while fetching track %s", normalized_query)
                if progress_queue and progress_sentinel is not None:
                    progress_queue.put_nowait(progress_sentinel)
                if progress_task:
                    with contextlib.suppress(asyncio.CancelledError):
                        await progress_task
                progress_queue = None
                progress_task = None
                progress_sentinel = None
                if progress_message:
                    with contextlib.suppress(discord.HTTPException):
                        await progress_message.edit(content="Произошла ошибка при загрузке трека.", embed=None)
                else:
                    await message.reply("Произошла ошибка при загрузке трека.")
                return "Ошибка загрузки"
            finally:
                if progress_queue and progress_sentinel is not None:
                    progress_queue.put_nowait(progress_sentinel)
                if progress_task:
                    with contextlib.suppress(asyncio.CancelledError):
                        await progress_task

            tracks = [
                QueuedTrack(
                    source=src,
                    title=src.title,
                    requester=message.author,
                    stream_url=src.url if src.is_stream else None,
                    webpage_url=src.webpage_url,
                    thumbnail=src.thumbnail,
                    uploader=src.uploader,
                    duration=src.duration,
                    local_path=src.local_path,
                )
                for src in sources
            ]

            if not tracks:
                await message.reply("Не удалось найти трек по этому запросу.")
                return "Трек не найден"

            for track in tracks:
                self.queue.append(track)

            embed = self._build_track_embed(tracks[0], color=discord.Color.blue())
            if progress_message:
                with contextlib.suppress(discord.HTTPException):
                    await progress_message.edit(content=None, embed=embed)
            else:
                await message.reply(embed=embed)

            if voice_client.is_connected() and not voice_client.is_playing():
                await self._start_next_track()

            queued_titles = ", ".join(track.title for track in tracks)
            return f"Добавлено в очередь: {queued_titles}"

    async def skip_func(self, message: discord.Message) -> str:
        if not self.voice_client or not self.voice_client.is_playing():
            await message.reply("Сейчас ничего не играет.")
            return "Очередь не воспроизводится"

        skipped = self.current.title if self.current else "текущий трек"
        self.voice_client.stop()
        await message.reply(f"Пропускаю: {skipped}")
        return f"Пропущен трек: {skipped}"

    async def skip_by_name_func(self, message: discord.Message, song_name: str) -> str:
        lowercase_query = song_name.lower()
        for track in list(self.queue):
            if lowercase_query in track.title.lower():
                self.queue.remove(track)
                self._cleanup_track_file(track)
                await message.reply(f"Удалено из очереди: {track.title}")
                return f"Удалено из очереди: {track.title}"
        await message.reply("Такой трек не найден в очереди.")
        return "Трек не найден"

    async def stop_func(self, message: discord.Message) -> str:
        self._cleanup_queue()
        if self.voice_client:
            self.voice_client.stop()
        else:
            self._cleanup_track_file(self.current)
            self.current = None
        await message.reply("Очередь очищена и воспроизведение остановлено.")
        return "Очередь очищена"

    async def summon_func(self, message: discord.Message) -> str:
        voice_client = await self._ensure_voice_client(message)
        if not voice_client:
            return "Пользователь не в голосовом канале"
        await message.reply("Я уже с вами в канале!")
        return "Бот в голосовом канале"

    async def disconnect_func(self, message: discord.Message) -> str:
        if self.voice_client:
            await self.voice_client.disconnect(force=True)
            self.voice_client = None
        self._cleanup_queue()
        self._cleanup_track_file(self.current)
        self.current = None
        await message.reply("Отключилась от канала и очистила очередь.")
        return "Бот отключён"

    async def seek_func(self, message: discord.Message, time: str) -> str:
        if not self.voice_client or not self.voice_client.is_playing() or not self.current:
            await message.reply("Сейчас ничего не играет.")
            return "Нет трека для перемотки"

        try:
            seconds = parse_time(time)
        except ValueError:
            await message.reply("Неверный формат времени. Пример: 1:23 или 73")
            return "Некорректное время"

        if not self.current.stream_url and not self.current.local_path:
            await message.reply("Для этого трека перемотка недоступна.")
            return "Перемотка недоступна"

        source_url = self.current.stream_url or str(self.current.local_path)
        new_source = discord.FFmpegPCMAudio(
            source_url,
            before_options=f"-ss {seconds} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options=f"-vn -sn -dn -bufsize 64k -af {LOUDNESS_NORMALIZATION_FILTER}",
        )
        wrapped = discord.PCMVolumeTransformer(new_source)
        self.voice_client.stop()
        self.current.source = wrapped
        self.voice_client.play(self.current.source, after=self._after_playback)
        await message.reply(f"Перемотала на {format_duration(seconds)}")
        return f"Перемотала на {format_duration(seconds)}"

    async def set_volume_func(self, message: discord.Message, level: float) -> str:
        if not self.voice_client or not self.voice_client.is_playing():
            await message.reply("Сейчас ничего не играет.")
            return "Нет активного воспроизведения"
        if level < 0.0 or level > 2.0:
            await message.reply("Громкость должна быть в диапазоне 0.0-2.0.")
            return "Недопустимое значение громкости"

        source = self.voice_client.source
        if hasattr(source, "volume"):
            source.volume = level
            await message.reply(f"Громкость установлена на {int(level * 100)}%.")
            return f"Громкость {int(level * 100)}%"
        await message.reply("Невозможно изменить громкость для этого источника.")
        return "Громкость недоступна"

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
        now = discord.utils.utcnow()
        last = self._last_audio_time or now
        if (now - last).total_seconds() > 25:
            await self._restart_current_stream()

    @monitor_stalled_playback.before_loop
    async def before_monitor_stalled_playback(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def check_for_inactivity(self) -> None:
        now = discord.utils.utcnow()
        for vc in list(self.bot.voice_clients):
            if not vc.is_playing() and not vc.is_paused():
                last_time = self._last_audio_time or now
                if (now - last_time).total_seconds() > 1800:
                    await vc.disconnect()
        if not self.voice_client or not self.voice_client.is_connected():
            self._cleanup_queue()
            self._cleanup_track_file(self.current)
            self.current = None

    @check_for_inactivity.before_loop
    async def before_check_for_inactivity(self) -> None:
        await self.bot.wait_until_ready()
