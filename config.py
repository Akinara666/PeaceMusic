
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


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
class ElevenLabsSettings:
    api_key: str


@dataclass(frozen=True)
class TelegramSettings:
    api_id: int
    api_hash: str
    session_name: str = "session"


@dataclass(frozen=True)
class SpotifySettings:
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class MiscSettings:
    deepseek_base_url: Optional[str]
    hailuo_api_key: Optional[str]
    genius_access_token: Optional[str]
    tenor_api_key: Optional[str]
    music_directory: Path
    context_file: Path
    status_message: str


@dataclass(frozen=True)
class AppSettings:
    discord: DiscordSettings
    gemini: GeminiSettings
    elevenlabs: Optional[ElevenLabsSettings]
    telegram: Optional[TelegramSettings]
    spotify: Optional[SpotifySettings]
    misc: MiscSettings


def _build_intents() -> discord.Intents:
    intents = discord.Intents.all()
    intents.message_content = True
    intents.members = True
    intents.guilds = True
    intents.messages = True
    intents.voice_states = True
    return intents


def load_settings() -> AppSettings:
    discord_token = _get_env('DISCORD_BOT_TOKEN', required=True)
    chatbot_channel_id_raw = _get_env('CHATBOT_CHANNEL_ID')
    chatbot_channel_id = int(chatbot_channel_id_raw) if chatbot_channel_id_raw else None

    gemini_key = _get_env('GEMINI_API_KEY', required=True)

    elevenlabs_key = _get_env('ELEVENLABS_API_KEY')
    telegram_api_id = _get_env('TELEGRAM_API_ID')
    telegram_api_hash = _get_env('TELEGRAM_API_HASH')
    telegram_session = _get_env('TELEGRAM_SESSION_NAME', default='session')
    spotify_client_id = _get_env('SPOTIFY_CLIENT_ID')
    spotify_client_secret = _get_env('SPOTIFY_CLIENT_SECRET')
    deepseek_base_url = _get_env('DEEPSEEK_BASE_URL')
    hailuo_api_key = _get_env('HAILUO_API_KEY')
    genius_access_token = _get_env('GENIUS_ACCESS_TOKEN')
    tenor_api_key = _get_env('TENOR_API_KEY')
    music_directory = Path(_get_env('MUSIC_DIRECTORY', default='music_files') or 'music_files')
    context_file = Path(_get_env('CONTEXT_FILE', default='chat_context.json') or 'chat_context.json')
    status_message = _get_env('DISCORD_STATUS_MESSAGE', default='Серегу пирата') or 'Серегу пирата'

    elevenlabs_settings = ElevenLabsSettings(api_key=elevenlabs_key) if elevenlabs_key else None

    telegram_settings = None
    if telegram_api_id and telegram_api_hash:
        telegram_settings = TelegramSettings(
            api_id=int(telegram_api_id),
            api_hash=telegram_api_hash,
            session_name=telegram_session or 'session',
        )

    spotify_settings = None
    if spotify_client_id and spotify_client_secret:
        spotify_settings = SpotifySettings(
            client_id=spotify_client_id,
            client_secret=spotify_client_secret,
        )

    misc_settings = MiscSettings(
        deepseek_base_url=deepseek_base_url,
        hailuo_api_key=hailuo_api_key,
        genius_access_token=genius_access_token,
        tenor_api_key=tenor_api_key,
        music_directory=music_directory,
        context_file=context_file,
        status_message=status_message,
    )

    return AppSettings(
        discord=DiscordSettings(
            token=discord_token,
            chatbot_channel_id=chatbot_channel_id,
            intents=_build_intents(),
        ),
        gemini=GeminiSettings(api_key=gemini_key),
        elevenlabs=elevenlabs_settings,
        telegram=telegram_settings,
        spotify=spotify_settings,
        misc=misc_settings,
    )


_settings = load_settings()

# Backwards-compatible module-level aliases ---------------------------------
DISCORD_BOT_TOKEN = _settings.discord.token
CHATBOT_CHANNEL_ID = _settings.discord.chatbot_channel_id
INTENTS = _settings.discord.intents
GEMINI_API_KEY = _settings.gemini.api_key
MUSIC_DIRECTORY = _settings.misc.music_directory
DEEPSEEK_BASE_URL = _settings.misc.deepseek_base_url or ''
HAILUO_API_KEY = _settings.misc.hailuo_api_key or ''
GENIUS_ACCESS_TOKEN = _settings.misc.genius_access_token or ''
TENOR_API_KEY = _settings.misc.tenor_api_key or ''
CONTEXT_FILE = str(_settings.misc.context_file)
DISCORD_STATUS_MESSAGE = _settings.misc.status_message

ELEVENLABS_API_KEY = _settings.elevenlabs.api_key if _settings.elevenlabs else ''
TELEGRAM_API_ID = _settings.telegram.api_id if _settings.telegram else None
TELEGRAM_API_HASH = _settings.telegram.api_hash if _settings.telegram else ''
TELEGRAM_SESSION_NAME = _settings.telegram.session_name if _settings.telegram else 'session'
SPOTIFY_CLIENT_ID = _settings.spotify.client_id if _settings.spotify else ''
SPOTIFY_CLIENT_SECRET = _settings.spotify.client_secret if _settings.spotify else ''


def get_settings() -> AppSettings:
    """Return the cached application settings."""
    return _settings
