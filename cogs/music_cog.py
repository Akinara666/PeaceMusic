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
    # Low resource optimization: fast extraction, no downloads
    "cookiefile": str(COOKIES_PATH),
    "format": "bestaudio[abr<=96]/worst", # Low bitrate for stability
    "noplaylist": True,
    "nopart": True,
    "default_search": "ytsearch1",
    "http_chunk_size": 10_485_760, # 10MB chunk for fewer requests
    "forceipv4": True,
    
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Referer": "https://www.youtube.com/",
        "Origin":  "https://www.youtube.com",
    },

    "hls_prefer_native": True, 
    "extractor_args": {
        "youtube": {
            "skip": ["dash", "hls"], # Skip DASH/HLS manifests if possible for speed
            "player_client": ["android", "web"], # Android client often faster/lighter
        }
    },
    
    "quiet": True,
    "no_warnings": True,
    "socket_timeout": 10,
    "retries": 3,
}

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-reconnect_at_eof 1 -reconnect_on_network_error 1 "
        "-nostdin"
    ),
    "options": (
        "-vn -sn -dn "
        "-bufsize 4M "     # Larger buffer to prevent stuttering
        "-probesize 1M "   # Larger probe size for better format detection
        "-ac 2 "           # Force stereo
        "-ar 48000 "
        "-threads 1 "      # Limit threads
        "-loglevel error"
    ),
}


ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

@dataclass
class QueuedTrack:
    query: str
    requester: discord.abc.User
    channel: Optional[discord.abc.Messageable]
    title: str = "Загрузка..." # Placeholder
    webpage_url: Optional[str] = None
    source: Optional[discord.AudioSource] = None
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None

class YTDLSource(discord.FFmpegPCMAudio):
    def __init__(self, source: str, *, data: dict):
        super().__init__(source, **FFMPEG_OPTIONS)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")
        self.duration = data.get("duration")
        self.uploader = data.get("uploader")
        self.thumbnail = data.get("thumbnail")
        self.webpage_url = data.get("webpage_url")

    @classmethod
    async def create_source(cls, query: str, *, loop: asyncio.AbstractEventLoop = None) -> YTDLSource:
        loop = loop or asyncio.get_event_loop()
        
        # 1. Extract Info (Fast, no download)
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))

        # Handle playlists/search results
        if "entries" in data:
            # take first item
            data = data["entries"][0]

        filename = data["url"]
        return cls(filename, data=data)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_client: Optional[discord.VoiceClient] = None
        self.queue: Deque[QueuedTrack] = deque()
        self.current: Optional[QueuedTrack] = None
        self._play_lock = asyncio.Lock()
        
        self.check_for_inactivity.start()

    def cog_unload(self):
        self.check_for_inactivity.cancel()

    async def _ensure_voice_client(self, message: discord.Message) -> Optional[discord.VoiceClient]:
        author = message.author
        if not author.voice or not author.voice.channel:
            await message.reply("Ты не подключен к голосовому каналу.")
            return None

        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel != author.voice.channel:
                await self.voice_client.move_to(author.voice.channel)
        else:
            self.voice_client = await author.voice.channel.connect(timeout=10, self_deaf=True) # self_deaf saves bandwidth
        return self.voice_client

    async def _start_next_track(self) -> None:
        if not self.voice_client or not self.voice_client.is_connected():
            return
        
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            return

        if not self.queue:
            self.current = None
            return

        # Pop next track (which only has metadata/query)
        self.current = self.queue.popleft()
        
        # Notify user processing started (optional, maybe too spammy? Let's just log)
        logger.info(f"Processing next track: {self.current.query}")

        try:
            # JIT Extraction
            source = await YTDLSource.create_source(self.current.query, loop=self.bot.loop)
            
            # Update track detailed info
            self.current.source = source
            self.current.title = source.title
            self.current.webpage_url = source.webpage_url
            self.current.duration = source.duration
            self.current.uploader = source.uploader
            self.current.thumbnail = source.thumbnail

            self.voice_client.play(source, after=self._after_playback)
            
            # Announce Now Playing
            if self.current.channel:
                embed = self._build_track_embed(self.current, description="Сейчас играет", color=discord.Color.green())
                await self.current.channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Failed to play track {self.current.query}: {e}")
            if self.current.channel:
                await self.current.channel.send(f"Ошибка воспроизведения трека: {e}")
            self._after_playback(e) # Skip to next

    def _after_playback(self, error: Optional[Exception]) -> None:
        if error:
            logger.error(f"Playback error: {error}")
        
        self.current = None
        # Schedule next track safely
        self.bot.loop.call_soon_threadsafe(asyncio.create_task, self._start_next_track())

    def _build_track_embed(self, track: QueuedTrack, *, color: discord.Color, description: str = "") -> discord.Embed:
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
        if track.duration:
            embed.add_field(name="Длительность", value=format_duration(track.duration), inline=True)
        return embed

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------
    
    @tasks.loop(minutes=5)
    async def check_for_inactivity(self):
        if self.voice_client and self.voice_client.is_connected():
            # If alone in channel or not playing for a long time, disconnect
            if len(self.voice_client.channel.members) == 1: # Only bot
                await self.voice_client.disconnect()
                self.voice_client = None
                self.queue.clear()
            elif not self.voice_client.is_playing() and not self.queue:
                # Idle for 5 mins
                await self.voice_client.disconnect()
                self.voice_client = None


    # ------------------------------------------------------------------
    # Public functions used by the AI cog
    # ------------------------------------------------------------------

    async def play_func(self, message: discord.Message, song_name: str) -> str:
        async with self._play_lock:
            if not await self._ensure_voice_client(message):
                return "Не удалось подключиться к каналу."

            normalized_query = normalize_audio_query(song_name)
            
            # Lightweight append to queue
            track = QueuedTrack(
                query=normalized_query,
                requester=message.author,
                channel=message.channel,
                title=f"Запрос: {song_name}"
            )
            
            self.queue.append(track)
            
            # If not playing, start immediately (Async)
            if not self.voice_client.is_playing():
                asyncio.create_task(self._start_next_track())
                return f"🔍 Поиск и воспроизведение: {song_name}"
            else:
                return f"✅ Добавлено в очередь: {song_name} (Позиция: {len(self.queue)})"

    async def play_attachment_func(self, message: discord.Message, attachment: discord.Attachment) -> str:
        # For attachments, since we can't 'stream' them easily without URL expiry or downloading,
        # we might still need to download them OR use the attachment URL if it persists.
        # Discord attachment URLs expire, so downloading is safer.
        # BUT for optimization, let's treat it as a stream URL if possible, or skip optimization for attachments.
        # Optimization: Just use the URL. If it 403s later, that's the trade-off.
        
        async with self._play_lock:
            if not await self._ensure_voice_client(message):
                return "Не удалось подключиться к каналу."
            
            track = QueuedTrack(
                query=attachment.url,
                requester=message.author,
                channel=message.channel,
                title=attachment.filename
            )
            
            self.queue.append(track)
             
            if not self.voice_client.is_playing():
                asyncio.create_task(self._start_next_track())
                return f"▶️ Включаю файл: {attachment.filename}"
            else:
                return f"✅ Файл добавлен в очередь: {attachment.filename}"

    async def skip_func(self, message: discord.Message) -> str:
        if not self.voice_client or not self.voice_client.is_playing():
            return "Сейчас ничего не играет."

        skipped = self.current.title if self.current else "Unknown"
        self.voice_client.stop() # This triggers _after_playback which plays next
        await message.reply(f"Пропущен трек: {skipped}")
        return f"Пропущен: {skipped}"

    async def skip_by_name_func(self, message: discord.Message, song_name: str) -> str:
        if not self.queue:
            return "Очередь пуста."

        # Case-insensitive partial match
        lowered_name = song_name.lower()
        
        # We need to iterate and remove. modifying deque while iterating is tricky, 
        # so we'll look for index or rebuild. 
        # Since queue is small, rebuilding is fine or just rotating? 
        # Actually, let's just find the first match and remove it.
        
        removed_track = None
        for track in self.queue:
            # track.title might be "Загрузка..." if it's not processed yet, 
            # but track.query (URL or search term) is always there.
            # Best to check both or just title? User probably knows the title they asked for.
            # But if it's still "Загрузка...", searching by title might fail.
            # Let's search query too if title is placeholder.
            
            title_check = track.title.lower() if track.title else ""
            query_check = track.query.lower()
            
            if lowered_name in title_check or lowered_name in query_check:
                removed_track = track
                break
        
        if removed_track:
            self.queue.remove(removed_track)
            display_name = removed_track.title if removed_track.title != "Загрузка..." else removed_track.query
            return f"🗑️ Удалено из очереди: {display_name}"
        
        return f"Не найдено в очереди: {song_name}"

    async def stop_func(self, message: discord.Message) -> str:
        self.queue.clear()
        if self.voice_client:
            self.voice_client.stop()
        await message.reply("Очередь очищена, воспроизведение остановлено.")
        return "Стоп"

    async def summon_func(self, message: discord.Message) -> str:
        await self._ensure_voice_client(message)
        return "Я здесь."

    async def disconnect_func(self, message: discord.Message) -> str:
        if self.voice_client:
            await self.voice_client.disconnect()
            self.voice_client = None
        self.queue.clear()
        return "Отключилась."

    async def seek_func(self, message: discord.Message, time: str) -> str:
        return "Перемотка недоступна в режиме онлайн-стриминга."

    async def set_volume_func(self, message: discord.Message, level: float) -> str:
        return "⚠️ Регулировка громкости отключена для повышения производительности."
