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
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()


def _get_env(
    name: str, default: Optional[str] = None, *, required: bool = False
) -> Optional[str]:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(
            f"Required environment variable '{name}' is missing. "
            "Populate it via environment or a .env file at the project root."
        )
    return value


def _get_env_bool(name: str, default: bool = False) -> bool:
    value = _get_env(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


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
    response_model: str = "gemini-3.1-flash-lite-preview"
    summary_model: str = "gemini-3.1-flash-lite-preview"
    embedding_model: str = "gemini-embedding-2-preview"
    embedding_dimensions: int = 768
    thinking_budget: int = 8192
    socks_proxy: Optional[str] = None

    @property
    def default_model(self) -> str:
        return self.response_model


@dataclass(frozen=True)
class MemorySettings:
    db_file: Path
    recent_messages_limit: int
    semantic_results_limit: int
    semantic_min_score: float
    summary_trigger_messages: int
    summary_window_messages: int


@dataclass(frozen=True)
class MiscSettings:
    music_directory: Path
    status_message: str
    prompt_file: Optional[Path]
    prompt_text: str
    rate_limit_max_requests: int = 0
    rate_limit_window_seconds: float = 60.0
    queue_max_size: int = 50


@dataclass(frozen=True)
class AudioSettings:
    ytdl_options: dict
    ffmpeg_options: dict


@dataclass(frozen=True)
class AppSettings:
    discord: DiscordSettings
    gemini: GeminiSettings
    memory: MemorySettings
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


def _build_ytdl_options(
    music_dir: Path,
    *,
    use_cookies: bool,
    cookies_file: Optional[Path],
) -> dict:
    """
    Optimized for 1 vCPU / 2GB RAM.
    - format: Prefer opus/webm when available to reduce transcoding overhead.
    - buffers: Modest chunk sizes to avoid OOM but sufficient for stability.
    """
    options = {
        "format": "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio/best",
        "noplaylist": True,
        "ignoreerrors": False,
        "logtostderr": False,
        "default_search": "auto",
        "force_ipv4": False,
        "cachedir": False,
        "outtmpl": str(music_dir / "%(extractor)s-%(id)s.%(ext)s"),
        # Limits to prevent long hangs:
        "max_filesize": 50_000_000,
        # Optimized buffer/network settings
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 20,
    }
    if use_cookies and cookies_file is not None:
        options["cookiefile"] = str(cookies_file)
    return options


def _build_ffmpeg_options() -> dict:
    """
    Optimized for 1 vCPU / 2GB RAM.
    - threads 1: Prevent thread contention on single core.
    - bufsize/probesize: Increased to 4MB/2MB to handle network jitter.
    - reconnect: Separate policies for generic streams and YouTube HLS.
    """
    reconnect_args = (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-reconnect_at_eof 1 -reconnect_on_network_error 1 -reconnect_on_http_error 4xx,5xx "
        "-rw_timeout 15000000 "
        "-err_detect ignore_err "
    )
    youtube_hls_reconnect_args = (
        "-reconnect 1 -reconnect_delay_max 2 "
        "-reconnect_on_network_error 1 "
        "-rw_timeout 15000000 "
        "-err_detect ignore_err "
    )

    return {
        "before_options_stream": f"{reconnect_args} -nostdin",
        "before_options_stream_youtube_hls": (
            f"{youtube_hls_reconnect_args} -nostdin"
        ),
        "before_options_file": "-nostdin",
        "options": (
            "-vn -sn -dn "
            "-bufsize 4096k "  # 4MB buffer
            "-probesize 2048k "
            "-analyzeduration 0 "  # Speed up startup
            "-threads 1 "
            "-loglevel warning"
        ),
    }


def load_settings() -> AppSettings:
    discord_token = _get_env("DISCORD_BOT_TOKEN", required=True)
    chatbot_channel_id_raw = (_get_env("CHATBOT_CHANNEL_ID") or "").strip()
    chatbot_channel_id: Optional[int]
    if chatbot_channel_id_raw:
        try:
            chatbot_channel_id = int(chatbot_channel_id_raw)
        except ValueError as exc:
            raise RuntimeError(
                f"CHATBOT_CHANNEL_ID must be an integer, got {chatbot_channel_id_raw!r}"
            ) from exc
    else:
        chatbot_channel_id = None

    gemini_key = _get_env("GEMINI_API_KEY", required=True)
    gemini_response_model = (
        _get_env("GEMINI_RESPONSE_MODEL")
        or _get_env("GEMINI_MODEL")
        or "gemini-3.1-flash-lite-preview"
    )
    gemini_summary_model = (
        _get_env("GEMINI_SUMMARY_MODEL") or "gemini-3.1-flash-lite-preview"
    )
    gemini_embedding_model = (
        _get_env("GEMINI_EMBEDDING_MODEL") or "gemini-embedding-2-preview"
    )
    gemini_embedding_dimensions = int(
        _get_env("GEMINI_EMBEDDING_DIMENSIONS", default="768") or "768"
    )
    gemini_thinking_budget = int(
        _get_env("GEMINI_THINKING_BUDGET", default="8192") or "8192"
    )
    gemini_socks_proxy = _get_env("GEMINI_SOCKS_PROXY") or None

    music_directory = Path(
        _get_env("MUSIC_DIRECTORY", default="music_files") or "music_files"
    )

    memory_db_file = Path(
        _get_env("CHAT_MEMORY_DB", default="chat_memory.sqlite3")
        or "chat_memory.sqlite3"
    )
    status_message = (
        _get_env("DISCORD_STATUS_MESSAGE", default="PeaceMusic") or "PeaceMusic"
    )
    recent_messages_limit = int(
        _get_env("MEMORY_RECENT_MESSAGES", default="12") or "12"
    )
    semantic_results_limit = int(
        _get_env("MEMORY_SEMANTIC_RESULTS", default="6") or "6"
    )
    semantic_min_score = float(
        _get_env("MEMORY_SEMANTIC_MIN_SCORE", default="0.35") or "0.35"
    )
    summary_trigger_messages = int(
        _get_env("MEMORY_SUMMARY_TRIGGER", default="30") or "30"
    )
    summary_window_messages = int(
        _get_env("MEMORY_SUMMARY_WINDOW", default="40") or "40"
    )

    prompt_file_raw = _get_env("BOT_PROMPT_FILE")
    ytdl_use_cookies = _get_env_bool("YTDL_USE_COOKIES", default=False)
    cookies_file_raw = (
        _get_env("YTDL_COOKIE_FILE") or "data/cookies.txt"
    )
    cookies_file: Optional[Path] = None
    if ytdl_use_cookies:
        candidate = Path(cookies_file_raw)
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        cookies_file = candidate
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

    rate_limit_max_requests = int(
        _get_env("AI_RATE_LIMIT_MAX_REQUESTS", default="20") or "20"
    )
    rate_limit_window_seconds = float(
        _get_env("AI_RATE_LIMIT_WINDOW_SECONDS", default="60") or "60"
    )

    queue_max_size = int(_get_env("MUSIC_QUEUE_MAX_SIZE", default="50") or "50")

    misc_settings = MiscSettings(
        music_directory=music_directory,
        status_message=status_message,
        prompt_file=prompt_file,
        prompt_text=prompt_text,
        rate_limit_max_requests=rate_limit_max_requests,
        rate_limit_window_seconds=rate_limit_window_seconds,
        queue_max_size=queue_max_size,
    )

    memory_settings = MemorySettings(
        db_file=memory_db_file,
        recent_messages_limit=recent_messages_limit,
        semantic_results_limit=semantic_results_limit,
        semantic_min_score=semantic_min_score,
        summary_trigger_messages=summary_trigger_messages,
        summary_window_messages=summary_window_messages,
    )

    audio_settings = AudioSettings(
        ytdl_options=_build_ytdl_options(
            music_directory,
            use_cookies=ytdl_use_cookies,
            cookies_file=cookies_file,
        ),
        ffmpeg_options=_build_ffmpeg_options(),
    )

    return AppSettings(
        discord=DiscordSettings(
            token=discord_token,
            chatbot_channel_id=chatbot_channel_id,
            intents=_build_intents(),
        ),
        gemini=GeminiSettings(
            api_key=gemini_key,
            response_model=gemini_response_model,
            summary_model=gemini_summary_model,
            embedding_model=gemini_embedding_model,
            embedding_dimensions=gemini_embedding_dimensions,
            thinking_budget=gemini_thinking_budget,
            socks_proxy=gemini_socks_proxy,
        ),
        memory=memory_settings,
        misc=misc_settings,
        audio=audio_settings,
    )


_settings = load_settings()

# Backwards-compatible module-level aliases ---------------------------------
DISCORD_BOT_TOKEN = _settings.discord.token
CHATBOT_CHANNEL_ID = _settings.discord.chatbot_channel_id
INTENTS = _settings.discord.intents
GEMINI_API_KEY = _settings.gemini.api_key
GEMINI_MODEL = _settings.gemini.response_model
GEMINI_SUMMARY_MODEL = _settings.gemini.summary_model
GEMINI_EMBEDDING_MODEL = _settings.gemini.embedding_model
GEMINI_EMBEDDING_DIMENSIONS = _settings.gemini.embedding_dimensions
GEMINI_THINKING_BUDGET = _settings.gemini.thinking_budget
GEMINI_SOCKS_PROXY = _settings.gemini.socks_proxy
MUSIC_DIRECTORY = _settings.misc.music_directory

CHAT_MEMORY_DB = str(_settings.memory.db_file)
MEMORY_RECENT_MESSAGES = _settings.memory.recent_messages_limit
MEMORY_SEMANTIC_RESULTS = _settings.memory.semantic_results_limit
MEMORY_SEMANTIC_MIN_SCORE = _settings.memory.semantic_min_score
MEMORY_SUMMARY_TRIGGER = _settings.memory.summary_trigger_messages
MEMORY_SUMMARY_WINDOW = _settings.memory.summary_window_messages
DISCORD_STATUS_MESSAGE = _settings.misc.status_message
BOT_PROMPT_FILE = (
    str(_settings.misc.prompt_file) if _settings.misc.prompt_file else None
)
BOT_PROMPT_TEXT = _settings.misc.prompt_text
YTDL_OPTIONS = _settings.audio.ytdl_options
FFMPEG_OPTIONS = _settings.audio.ffmpeg_options
MUSIC_QUEUE_MAX_SIZE = _settings.misc.queue_max_size


def get_settings() -> AppSettings:
    """Return the cached application settings."""
    return _settings
