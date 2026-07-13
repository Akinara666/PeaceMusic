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
    value = os.getenv(name)
    file_name = os.getenv(f"{name}_FILE")
    if value is None and file_name:
        try:
            value = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(
                f"Unable to read {name}_FILE from {file_name!r}: {exc}"
            ) from exc
    if value is None:
        value = default
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
    raise RuntimeError(
        f"{name} must be a boolean (true/false, yes/no, on/off, 1/0), got {value!r}"
    )


def _get_env_int(name: str, default: int) -> int:
    """Read an integer env var, falling back to ``default`` when unset/empty.

    Raises ``RuntimeError`` with a clear message for non-integer values so a
    typo in the environment fails fast instead of crashing deep in startup.
    """
    raw = (_get_env(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc


def _get_env_float(name: str, default: float) -> float:
    """Read a float env var, falling back to ``default`` when unset/empty."""
    raw = (_get_env(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number, got {raw!r}") from exc


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


def _validate_cookie_file(path: Path) -> None:
    """Fail at startup when enabled cookies are missing or malformed."""
    try:
        with path.open("r", encoding="utf-8") as cookie_file:
            header = cookie_file.readline().strip()
    except OSError as exc:
        raise RuntimeError(
            f"YTDL_COOKIE_FILE is not readable at {str(path)!r}: {exc}"
        ) from exc

    valid_headers = {"# HTTP Cookie File", "# Netscape HTTP Cookie File"}
    if header not in valid_headers:
        raise RuntimeError(
            "YTDL_COOKIE_FILE must be a Mozilla/Netscape cookies file; "
            f"invalid header in {str(path)!r}"
        )


@dataclass(frozen=True)
class DiscordSettings:
    token: str
    chatbot_channel_id: Optional[int]
    intents: discord.Intents


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str
    response_model: str = "gemini-3.1-flash-lite"
    summary_model: str = "gemini-3.1-flash-lite"
    embedding_model: str = "gemini-embedding-2"
    embedding_dimensions: int = 768
    thinking_budget: int = 8192
    temperature: float = 1.0
    top_p: float = 0.95
    request_timeout_ms: int = 24000
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
    semantic_half_life_days: float = 30.0
    semantic_candidate_limit: int = 1000
    raw_retention_days: int = 90


@dataclass(frozen=True)
class MiscSettings:
    music_directory: Path
    status_message: str
    prompt_file: Optional[Path]
    prompt_text: str
    rate_limit_max_requests: int = 0
    rate_limit_window_seconds: float = 60.0
    queue_max_size: int = 50
    ai_attachment_max_bytes: int = 25_000_000
    music_attachment_max_bytes: int = 25_000_000
    attachment_max_count: int = 4
    ai_max_concurrent_turns: int = 4
    ai_turn_timeout_seconds: float = 120.0
    require_mention_when_unscoped: bool = True


@dataclass(frozen=True)
class AudioSettings:
    ytdl_options: dict
    ffmpeg_options: dict
    allowed_media_domains: tuple[str, ...]


@dataclass(frozen=True)
class AppSettings:
    discord: DiscordSettings
    gemini: GeminiSettings
    memory: MemorySettings
    misc: MiscSettings
    audio: AudioSettings


def _build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True
    intents.messages = True
    intents.voice_states = True
    intents.presences = False
    return intents


def _require_range(
    name: str,
    value: int | float,
    *,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
) -> None:
    if minimum is not None and value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}, got {value!r}")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"{name} must be <= {maximum}, got {value!r}")


def _build_ytdl_options(
    music_dir: Path,
    *,
    use_cookies: bool,
    cookies_file: Optional[Path],
    cache_dir: Path,
) -> dict:
    """
    Optimized for 1 vCPU / 2GB RAM.
    - format: Prefer opus/webm when available to reduce transcoding overhead.
    - buffers: Modest chunk sizes to avoid OOM but sufficient for stability.
    - cachedir: Persist yt-dlp's player/signature cache so the expensive
      YouTube JS player (n-sig deciphering) is not re-fetched on every track.

    NOTE: do not pin youtube `player_client` here. Letting yt-dlp pick its
    default clients keeps playback working as YouTube rolls out SABR/DRM
    experiments; hard-pinning clients (e.g. tv/web_safari) breaks extraction
    on datacenter IPs without a PO token.
    """
    options = {
        "format": "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio/best",
        "noplaylist": True,
        "ignoreerrors": False,
        "logtostderr": False,
        "default_search": "auto",
        "force_ipv4": False,
        # YouTube increasingly requires an external JS challenge solver.
        # Prefer yt-dlp's recommended runtime and retain Node.js as a local
        # installation fallback (Node 22+ is required by current yt-dlp-ejs).
        "js_runtimes": {"deno": {}, "node": {}},
        "cachedir": str(cache_dir),
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
        "before_options_stream_youtube_hls": (f"{youtube_hls_reconnect_args} -nostdin"),
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
    chatbot_channel_id: Optional[int] = (
        _get_env_int("CHATBOT_CHANNEL_ID", 0) if chatbot_channel_id_raw else None
    )

    gemini_key = _get_env("GEMINI_API_KEY", required=True)
    gemini_response_model = (
        _get_env("GEMINI_RESPONSE_MODEL")
        or _get_env("GEMINI_MODEL")
        or "gemini-3.1-flash-lite"
    )
    gemini_summary_model = _get_env("GEMINI_SUMMARY_MODEL") or "gemini-3.1-flash-lite"
    gemini_embedding_model = _get_env("GEMINI_EMBEDDING_MODEL") or "gemini-embedding-2"
    gemini_embedding_dimensions = _get_env_int("GEMINI_EMBEDDING_DIMENSIONS", 768)
    gemini_thinking_budget = _get_env_int("GEMINI_THINKING_BUDGET", 8192)
    gemini_temperature = _get_env_float("GEMINI_TEMPERATURE", 1.0)
    gemini_top_p = _get_env_float("GEMINI_TOP_P", 0.95)
    gemini_request_timeout_ms = _get_env_int("GEMINI_REQUEST_TIMEOUT_MS", 24000)
    gemini_socks_proxy = _get_env("GEMINI_SOCKS_PROXY") or None

    _require_range(
        "GEMINI_EMBEDDING_DIMENSIONS",
        gemini_embedding_dimensions,
        minimum=128,
        maximum=3072,
    )
    _require_range("GEMINI_TEMPERATURE", gemini_temperature, minimum=0.0, maximum=2.0)
    _require_range("GEMINI_TOP_P", gemini_top_p, minimum=0.0, maximum=1.0)
    _require_range("GEMINI_REQUEST_TIMEOUT_MS", gemini_request_timeout_ms, minimum=1)

    music_directory = Path(
        _get_env("MUSIC_DIRECTORY", default="music_files") or "music_files"
    )
    if not music_directory.is_absolute():
        music_directory = (REPO_ROOT / music_directory).resolve()

    memory_db_file = Path(
        _get_env("CHAT_MEMORY_DB", default="chat_memory.sqlite3")
        or "chat_memory.sqlite3"
    )
    status_message = (
        _get_env("DISCORD_STATUS_MESSAGE", default="PeaceMusic") or "PeaceMusic"
    )
    recent_messages_limit = _get_env_int("MEMORY_RECENT_MESSAGES", 12)
    semantic_results_limit = _get_env_int("MEMORY_SEMANTIC_RESULTS", 6)
    semantic_min_score = _get_env_float("MEMORY_SEMANTIC_MIN_SCORE", 0.35)
    summary_trigger_messages = _get_env_int("MEMORY_SUMMARY_TRIGGER", 30)
    summary_window_messages = _get_env_int("MEMORY_SUMMARY_WINDOW", 40)
    semantic_half_life_days = _get_env_float("MEMORY_SEMANTIC_HALF_LIFE_DAYS", 30.0)
    semantic_candidate_limit = _get_env_int("MEMORY_SEMANTIC_CANDIDATES", 1000)
    raw_retention_days = _get_env_int("MEMORY_RAW_RETENTION_DAYS", 90)

    _require_range("MEMORY_RECENT_MESSAGES", recent_messages_limit, minimum=1)
    _require_range("MEMORY_SEMANTIC_RESULTS", semantic_results_limit, minimum=0)
    _require_range(
        "MEMORY_SEMANTIC_MIN_SCORE", semantic_min_score, minimum=0.0, maximum=1.0
    )
    _require_range("MEMORY_SUMMARY_TRIGGER", summary_trigger_messages, minimum=1)
    _require_range("MEMORY_SUMMARY_WINDOW", summary_window_messages, minimum=1)
    _require_range("MEMORY_SEMANTIC_HALF_LIFE_DAYS", semantic_half_life_days, minimum=0)
    _require_range("MEMORY_SEMANTIC_CANDIDATES", semantic_candidate_limit, minimum=1)
    _require_range("MEMORY_RAW_RETENTION_DAYS", raw_retention_days, minimum=0)
    if semantic_results_limit > semantic_candidate_limit:
        raise RuntimeError(
            "MEMORY_SEMANTIC_RESULTS cannot exceed MEMORY_SEMANTIC_CANDIDATES"
        )

    # Persistent yt-dlp cache. Defaults under data/ so it lands in the mounted
    # Docker volume (alongside the chat DB) and survives container restarts.
    ytdl_cache_dir_raw = (
        _get_env("YTDL_CACHE_DIR", default="data/ytdl_cache") or "data/ytdl_cache"
    )
    ytdl_cache_dir = Path(ytdl_cache_dir_raw)
    if not ytdl_cache_dir.is_absolute():
        ytdl_cache_dir = (REPO_ROOT / ytdl_cache_dir).resolve()

    prompt_file_raw = _get_env("BOT_PROMPT_FILE")
    ytdl_use_cookies = _get_env_bool("YTDL_USE_COOKIES", default=False)
    cookies_file_raw = _get_env("YTDL_COOKIE_FILE") or "data/cookies.txt"
    cookies_file: Optional[Path] = None
    if ytdl_use_cookies:
        candidate = Path(cookies_file_raw)
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        _validate_cookie_file(candidate)
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

    rate_limit_max_requests = _get_env_int("AI_RATE_LIMIT_MAX_REQUESTS", 20)
    rate_limit_window_seconds = _get_env_float("AI_RATE_LIMIT_WINDOW_SECONDS", 60.0)

    queue_max_size = _get_env_int("MUSIC_QUEUE_MAX_SIZE", 50)
    ai_attachment_max_bytes = _get_env_int("AI_ATTACHMENT_MAX_BYTES", 25_000_000)
    music_attachment_max_bytes = _get_env_int("MUSIC_ATTACHMENT_MAX_BYTES", 25_000_000)
    attachment_max_count = _get_env_int("AI_ATTACHMENT_MAX_COUNT", 4)
    ai_max_concurrent_turns = _get_env_int("AI_MAX_CONCURRENT_TURNS", 4)
    ai_turn_timeout_seconds = _get_env_float("AI_TURN_TIMEOUT_SECONDS", 120.0)
    require_mention_when_unscoped = _get_env_bool(
        "AI_REQUIRE_MENTION_WHEN_UNSCOPED", default=True
    )

    _require_range("AI_RATE_LIMIT_MAX_REQUESTS", rate_limit_max_requests, minimum=0)
    _require_range("AI_RATE_LIMIT_WINDOW_SECONDS", rate_limit_window_seconds, minimum=0)
    _require_range("MUSIC_QUEUE_MAX_SIZE", queue_max_size, minimum=1)
    _require_range("AI_ATTACHMENT_MAX_BYTES", ai_attachment_max_bytes, minimum=1)
    _require_range("MUSIC_ATTACHMENT_MAX_BYTES", music_attachment_max_bytes, minimum=1)
    _require_range("AI_ATTACHMENT_MAX_COUNT", attachment_max_count, minimum=1)
    _require_range("AI_MAX_CONCURRENT_TURNS", ai_max_concurrent_turns, minimum=1)
    _require_range("AI_TURN_TIMEOUT_SECONDS", ai_turn_timeout_seconds, minimum=1)

    allowed_media_domains = tuple(
        domain.strip().lower().lstrip(".")
        for domain in (
            _get_env(
                "MEDIA_ALLOWED_DOMAINS",
                "youtube.com,youtu.be,music.youtube.com,soundcloud.com,on.soundcloud.com",
            )
            or ""
        ).split(",")
        if domain.strip()
    )

    misc_settings = MiscSettings(
        music_directory=music_directory,
        status_message=status_message,
        prompt_file=prompt_file,
        prompt_text=prompt_text,
        rate_limit_max_requests=rate_limit_max_requests,
        rate_limit_window_seconds=rate_limit_window_seconds,
        queue_max_size=queue_max_size,
        ai_attachment_max_bytes=ai_attachment_max_bytes,
        music_attachment_max_bytes=music_attachment_max_bytes,
        attachment_max_count=attachment_max_count,
        ai_max_concurrent_turns=ai_max_concurrent_turns,
        ai_turn_timeout_seconds=ai_turn_timeout_seconds,
        require_mention_when_unscoped=require_mention_when_unscoped,
    )

    memory_settings = MemorySettings(
        db_file=memory_db_file,
        recent_messages_limit=recent_messages_limit,
        semantic_results_limit=semantic_results_limit,
        semantic_min_score=semantic_min_score,
        summary_trigger_messages=summary_trigger_messages,
        summary_window_messages=summary_window_messages,
        semantic_half_life_days=semantic_half_life_days,
        semantic_candidate_limit=semantic_candidate_limit,
        raw_retention_days=raw_retention_days,
    )

    audio_settings = AudioSettings(
        ytdl_options=_build_ytdl_options(
            music_directory,
            use_cookies=ytdl_use_cookies,
            cookies_file=cookies_file,
            cache_dir=ytdl_cache_dir,
        ),
        ffmpeg_options=_build_ffmpeg_options(),
        allowed_media_domains=allowed_media_domains,
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
            temperature=gemini_temperature,
            top_p=gemini_top_p,
            request_timeout_ms=gemini_request_timeout_ms,
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
AI_ATTACHMENT_MAX_BYTES = _settings.misc.ai_attachment_max_bytes
MUSIC_ATTACHMENT_MAX_BYTES = _settings.misc.music_attachment_max_bytes
AI_ATTACHMENT_MAX_COUNT = _settings.misc.attachment_max_count
MEDIA_ALLOWED_DOMAINS = _settings.audio.allowed_media_domains


def get_settings() -> AppSettings:
    """Return the cached application settings."""
    return _settings
