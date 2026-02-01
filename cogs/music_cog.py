
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

from config import MUSIC_DIRECTORY, YTDL_OPTIONS, FFMPEG_OPTIONS

logger = logging.getLogger(__name__)

MUSIC_DIRECTORY_PATH = Path(MUSIC_DIRECTORY)
MUSIC_DIRECTORY_PATH.mkdir(parents=True, exist_ok=True)


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


def build_ffmpeg_options(stream: bool, *, seek: Optional[int] = None) -> dict[str, str]:
    before = FFMPEG_OPTIONS["before_options_stream"] if stream else FFMPEG_OPTIONS["before_options_file"]
    if seek is not None and seek > 0:
        before = f"-ss {seek} {before}"
    return {
        "before_options": before,
        "options": FFMPEG_OPTIONS["options"],
    }

ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)


INFO_CACHE_TTL_SECONDS = 900
_info_cache: dict[str, tuple[float, dict]] = {}


async def _probe_info(url: str, *, loop: Optional[asyncio.AbstractEventLoop] = None) -> dict:
    """Быстрое получение метаданных без скачивания, с кэшем."""
    loop = loop or asyncio.get_event_loop()
    cache_key = f"1:{url}"
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
        stream: bool = True,
        on_chunk: Optional[Callable[[], None]] = None,
        start_at: Optional[int] = None,
    ) -> list["YTDLSource"]:
        loop = loop or asyncio.get_event_loop()
        
        cache_key = f"{int(stream)}:{url}"
        cached = _info_cache.get(cache_key)
        now = time.monotonic()
        
        if cached and (now - cached[0]) < INFO_CACHE_TTL_SECONDS:
            data = cached[1]
            logger.debug("yt_dlp extract_info cache hit for %s", url)
        else:
            start_time = time.monotonic()
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
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
                filename = ytdl.prepare_filename(entry)
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
    channel: Optional[discord.abc.Messageable] = None


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

        # Notify "Now Playing"
        if self.current.channel:
            embed = self._build_track_embed(
                self.current, 
                color=discord.Color.green(), 
                description="Сейчас играет"
            )
            self.bot.loop.create_task(self.current.channel.send(embed=embed))

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

    def _build_track_embed(self, track: QueuedTrack, *, color: discord.Color, description: str = "Трек добавлен в очередь") -> discord.Embed:
        embed = discord.Embed(
            title=track.title,
            url=track.webpage_url or discord.Embed.Empty,
            description=description,
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
            if normalized_query != song_name:
                logger.debug("Normalized audio query from %s to %s", song_name, normalized_query)

            # Streaming by default for 1 CPU / 2 GB RAM optimization
            # Avoids disk IO and startup delays.
            should_stream = True
            msg = await message.reply("Ищу и готовлю трек...")

            try:
                sources = await YTDLSource.from_url(
                    normalized_query,
                    loop=self.bot.loop,
                    stream=should_stream,
                    on_chunk=self._touch_audio_heartbeat,
                )
            except DownloadError as exc:
                logger.warning("Failed to download track %s: %s", normalized_query, exc)
                await msg.edit(content=f"Ошибка при поиске: {exc}")
                return "Ошибка поиска"
            except Exception as exc:  # noqa: BLE001
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.exception("Unexpected error while fetching track %s", normalized_query)
                await msg.edit(content="Произошла непредвиденная ошибка.")
                return "Ошибка поиска"

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
                    channel=message.channel,
                )
                for src in sources
            ]

            if not tracks:
                await msg.edit(content="Не удалось найти трек по этому запросу.")
                return "Трек не найден"

            for track in tracks:
                self.queue.append(track)

            embed = self._build_track_embed(tracks[0], color=discord.Color.blue())
            try:
                await msg.edit(content=None, embed=embed)
            except discord.HTTPException:
                pass

            if voice_client.is_connected() and not voice_client.is_playing():
                await self._start_next_track()

            queued_titles = ", ".join(track.title for track in tracks)
            if len(tracks) > 1:
                return f"Добавлено {len(tracks)} треков из плейлиста."
            return f"Добавлено в очередь: {queued_titles}"

    async def play_attachment_func(self, message: discord.Message, attachment: discord.Attachment) -> str:
        async with self._play_lock:
            voice_client = await self._ensure_voice_client(message)
            if not voice_client:
                return "Пользователь не в голосовом канале"

            # Save file with unique name
            safe_filename = Path(attachment.filename).name
            file_path = MUSIC_DIRECTORY_PATH / f"{int(time.time())}_{safe_filename}"
            
            try:
                await attachment.save(file_path)
            except Exception as exc:
                logger.warning("Failed to save attachment %s: %s", safe_filename, exc)
                return "Ошибка сохранения файла"

            ffmpeg_args = build_ffmpeg_options(stream=False)
            try:
                audio_source = discord.FFmpegPCMAudio(str(file_path), **ffmpeg_args)
            except Exception as exc:
                logger.error("Failed to create audio source for %s: %s", safe_filename, exc)
                with contextlib.suppress(OSError):
                    file_path.unlink()
                return "Ошибка обработки аудиофайла"

            track = QueuedTrack(
                source=audio_source,
                title=safe_filename,
                requester=message.author,
                local_path=file_path,
                webpage_url=attachment.url,
                channel=message.channel,
            )

            self.queue.append(track)

            embed = self._build_track_embed(track, color=discord.Color.green())
            await message.reply(embed=embed)

            if voice_client.is_connected() and not voice_client.is_playing():
                await self._start_next_track()

            return f"Добавлено в очередь: {track.title}"

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
        is_stream = self.current.stream_url is not None
        ffmpeg_args = build_ffmpeg_options(is_stream, seek=seconds)
        new_source = discord.FFmpegPCMAudio(source_url, **ffmpeg_args)
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
