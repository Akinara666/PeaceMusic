
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_PROMPT_PATH = REPO_ROOT / "utils" / "default_prompt.txt"
_FALLBACK_PROMPT = (
    "You are PeaceMusic, the assistant for a Discord music bot. Help users search, "
    "queue, play, pause, and otherwise control music playback. Respond in a concise, "
    "friendly tone, mention what actions you take, and keep users within the server "
    "rules. If a request is unclear or unsafe, ask for clarification or politely refuse."
)


def _load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()


def _get_env(name: str, default: Optional[str] = None, *, required: bool = False) -> Optional[str]:
    value = os.getenv(name, default)
    if required and (value is None or value == ''):
        raise RuntimeError(
            f"Required environment variable '{name}' is missing. "
            "Populate it via environment or a .env file at the project root."
        )
    return value


def _load_default_prompt() -> str:
    try:
        text = DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
        if text.strip():
            return text
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return _FALLBACK_PROMPT


@dataclass(frozen=True)
class DiscordSettings:
    token: str
    chatbot_channel_id: Optional[int]
    intents: discord.Intents


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str
    default_model: str = "gemini-2.5-flash"


@dataclass(frozen=True)
class MiscSettings:
    music_directory: Path
    context_file: Path
    status_message: str
    prompt_file: Optional[Path]
    prompt_text: str


@dataclass(frozen=True)
class AudioSettings:
    ytdl_options: dict
    ffmpeg_options: dict


@dataclass(frozen=True)
class AppSettings:
    discord: DiscordSettings
    gemini: GeminiSettings
    misc: MiscSettings
    audio: AudioSettings


def _build_intents() -> discord.Intents:
    intents = discord.Intents.all()
    intents.message_content = True
    intents.members = True
    intents.guilds = True
    intents.messages = True
    intents.voice_states = True
    return intents


def _build_ytdl_options(music_dir: Path) -> dict:
    """
    Optimized for 1 vCPU / 2GB RAM.
    - format: Prefer opus/webm (less transcoding).
    - quality: Cap at 96k (opus is transparent enough, saves CPU/Bandwidth).
    - buffers: Modest chunk sizes to avoid OOM but sufficient for stability.
    """
    cookies_path = REPO_ROOT / "cogs" / "cookies.txt"
    return {
        "cookiefile": str(cookies_path),
        "format": "bestaudio/best",
        "noplaylist": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "logtostderr": False,
        "default_search": "auto",
        "source_address": "0.0.0.0",
        
        # IPv6 often mitigates YouTube blocking on VPS IPv4 ranges.
        "forceipv4": False,
        
        "cachedir": False,
        "outtmpl": str(music_dir / "%(extractor)s-%(id)s.%(ext)s"),
        # Limits to prevent long hangs:
        "max_filesize": 50_000_000,
        
        # Optimized buffer/network settings
        "http_chunk_size": 10485760, 
        "socket_timeout": 60,        # Explicitly set to 60s
        "retries": 20,
        "fragment_retries": 20,
        
        # Use aria2c for robust downloading (multi-connection)
        # This is the best fix for throttling.
        "external_downloader": "aria2c",
        "external_downloader_args": [
            "-x", "8",   # 8 connections
            "-s", "8",   # 8 servers
            "-k", "1M"   # 1MB split
        ],
        
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
    }


def _build_ffmpeg_options() -> dict:
    """
    Optimized for 1 vCPU / 2GB RAM.
    - threads 1: Prevent thread contention on single core.
    - bufsize/probesize: Increased to 4MB/2MB to handle network jitter.
    - reconnect: Aggressive reconnection strategy.
    """
    reconnect_args = (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-reconnect_at_eof 1 -reconnect_on_network_error 1 -reconnect_on_http_error 4xx,5xx "
        "-rw_timeout 15000000 "
        "-err_detect ignore_err "
        "-user_agent \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\""
    )
    
    return {
        "before_options_stream": f"{reconnect_args} -nostdin",
        "before_options_file": "-nostdin",
        "options": (
            "-vn -sn -dn "
            "-bufsize 4096k "   # 4MB buffer
            "-probesize 2048k "
            "-analyzeduration 0 " # Speed up startup
            "-threads 1 "
            "-loglevel warning"
        ),
    }


def load_settings() -> AppSettings:
    discord_token = _get_env('DISCORD_BOT_TOKEN', required=True)
    chatbot_channel_id_raw = _get_env('CHATBOT_CHANNEL_ID')
    chatbot_channel_id = int(chatbot_channel_id_raw) if chatbot_channel_id_raw else None

    gemini_key = _get_env('GEMINI_API_KEY', required=True)

    music_directory = Path(_get_env('MUSIC_DIRECTORY', default='music_files') or 'music_files')
    context_file = Path(_get_env('CONTEXT_FILE', default='chat_context.json') or 'chat_context.json')
    status_message = _get_env('DISCORD_STATUS_MESSAGE', default='PeaceMusic') or 'PeaceMusic'

    prompt_file_raw = _get_env('BOT_PROMPT_FILE')
    prompt_file: Optional[Path] = None
    prompt_text = _load_default_prompt()
    if prompt_file_raw:
        candidate = Path(prompt_file_raw)
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        prompt_file = candidate
        try:
            loaded_text = candidate.read_text(encoding="utf-8")
            if loaded_text.strip():
                prompt_text = loaded_text
        except (FileNotFoundError, OSError):
            pass

    misc_settings = MiscSettings(
        music_directory=music_directory,
        context_file=context_file,
        status_message=status_message,
        prompt_file=prompt_file,
        prompt_text=prompt_text,
    )
    
    audio_settings = AudioSettings(
        ytdl_options=_build_ytdl_options(music_directory),
        ffmpeg_options=_build_ffmpeg_options(),
    )

    return AppSettings(
        discord=DiscordSettings(
            token=discord_token,
            chatbot_channel_id=chatbot_channel_id,
            intents=_build_intents(),
        ),
        gemini=GeminiSettings(api_key=gemini_key),
        misc=misc_settings,
        audio=audio_settings,
    )


_settings = load_settings()

# Backwards-compatible module-level aliases ---------------------------------
DISCORD_BOT_TOKEN = _settings.discord.token
CHATBOT_CHANNEL_ID = _settings.discord.chatbot_channel_id
INTENTS = _settings.discord.intents
GEMINI_API_KEY = _settings.gemini.api_key
MUSIC_DIRECTORY = _settings.misc.music_directory
CONTEXT_FILE = str(_settings.misc.context_file)
DISCORD_STATUS_MESSAGE = _settings.misc.status_message
BOT_PROMPT_FILE = str(_settings.misc.prompt_file) if _settings.misc.prompt_file else None
BOT_PROMPT_TEXT = _settings.misc.prompt_text
YTDL_OPTIONS = _settings.audio.ytdl_options
FFMPEG_OPTIONS = _settings.audio.ffmpeg_options


def get_settings() -> AppSettings:
    """Return the cached application settings."""
    return _settings
