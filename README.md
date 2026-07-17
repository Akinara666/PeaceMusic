<div align="center">

# PeaceMusic

**An AI‑native Discord bot that chats like a friend and runs your voice channel like a DJ.**

Powered by Google Gemini for conversation and tool‑calling, and by `yt‑dlp` + `FFmpeg` for music — with a multi‑layer SQLite memory so it actually remembers you.

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)](https://github.com/Rapptz/discord.py)
[![Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?logo=google&logoColor=white)](https://ai.google.dev/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](#license)

[Russian documentation →](README.ru.md)

</div>

---

## Table of Contents

- [Why PeaceMusic](#why-peacemusic)
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Docker Deployment](#docker-deployment)
- [Configuration](#configuration)
- [Usage](#usage)
- [Memory System](#memory-system)
- [Project Structure](#project-structure)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Why PeaceMusic

Most Discord music bots are just remote controls — type `!play`, get a song. PeaceMusic is built around a **conversational agent** that decides which actions to take. Ask it to *"throw on something chill from the 80s and skip when it gets boring"* and it will search, queue, monitor, and skip — invoking the right tools at the right time.

The bot stays coherent across long conversations through a layered memory system: recent turns, semantic recall via embeddings, and a rolling global summary. It can see images and videos you drop into chat and play audio attachments.

## Features

### Conversational AI
- **Gemini‑powered chat** with full tool‑calling: the model invokes music commands itself instead of you memorising syntax.
- **Private model reasoning** with a generic progress indicator; internal chain-of-thought is never posted to Discord.
- **Multimodal input** — drop images or short videos and the bot will reason about them via the Gemini API.
- **Per‑user access control** via the `/bot_access` slash command (requires *Manage Server*).
- **Per‑user rate limiting** with a configurable sliding window.

### Music Playback
- **YouTube and SoundCloud** — by trusted URL or natural‑language search. Additional domains can be explicitly allowlisted.
- **Queue management**: play, skip, skip‑by‑name, seek, pause/resume, volume (0.0–5.0×), shuffle, clear, remove by index, loop (off / track / queue).
- **Audio attachment auto‑play** — drop an `.mp3`/`.ogg`/`.wav` and the bot plays it.
- **Local cache** of downloaded tracks with bounded file size limits.
- **Resilient streaming**: tuned FFmpeg reconnect policy, separate HLS path for YouTube, IPv6‑aware.
- **Optional `yt‑dlp` cookies** for age‑restricted / region‑locked content.

### Operations
- **SOCKS5 proxy support** for all Gemini API traffic (responses, embeddings, summaries).
- **Graceful shutdown** on SIGTERM/SIGINT — disconnects voice cleanly and flushes pending summary tasks.
- **`uvloop`** for faster asyncio when available.
- **Docker / docker‑compose** ready, with persistent volumes for the memory DB and music cache.

---

## Architecture

```
┌─────────────────┐        ┌──────────────────────────────────────────────┐
│  Discord User   │──msg──▶│            GeminiChatCog (cogs/ai)           │
└─────────────────┘        │                                              │
                           │  ┌──────────────────────────────────────┐    │
                           │  │ MemoryStore (SQLite)                 │    │
                           │  │  • recent messages                   │    │
                           │  │  • semantic embeddings + decay       │    │
                           │  │  • rolling global summary            │    │
                           │  └──────────────────────────────────────┘    │
                           │                  ▼                           │
                           │  ┌──────────────────────────────────────┐    │
                           │  │ ResponseGenerator → Gemini API       │◀───┼── tool calls ──┐
                           │  │  (response model + thinking budget)  │    │                │
                           │  └──────────────────────────────────────┘    │                │
                           │                  │                           │                │
                           └──────────────────┼───────────────────────────┘                │
                                              ▼                                            │
                                       reply text                                          │
                                                                                           │
                           ┌──────────────────────────────────────────────┐                │
                           │             Music cog (cogs/music_cog)       │◀───────────────┘
                           │  yt‑dlp → FFmpeg → discord.VoiceClient       │
                           └──────────────────────────────────────────────┘
```

The chat cog owns a single Gemini client (shared by responses, embeddings, summaries, and file uploads) and a per‑channel asyncio lock so concurrent messages in the same channel are serialised. Tool calls are dispatched into the music cog and round‑tripped back to Gemini as `function_response` parts.

---

## Quick Start

### Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.10+** | 3.12 recommended (matches the Docker base image) |
| **FFmpeg** | Must be on `PATH` — required by `discord.FFmpegPCMAudio` |
| **Deno 2.3+** *or* **Node.js 22+** | Needed by `yt‑dlp` for YouTube signature extraction; Docker already includes Deno |
| **Discord Bot Token** | Create one at https://discord.com/developers/applications |
| **Gemini API Key** | Get one at https://aistudio.google.com/app/apikey |

> Enable the **Message Content**, **Server Members**, and **Voice State** intents in your bot's developer portal.

### Local installation

```bash
# 1. Clone
git clone https://github.com/Akinara666/PeaceMusic.git
cd PeaceMusic

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1

# 3. Dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Secrets
cp .env.example .env               # Windows: copy .env.example .env
# Edit .env — at minimum set DISCORD_BOT_TOKEN and GEMINI_API_KEY

# 5. Run
python main.py
```

---

## Docker Deployment

Recommended for any long-running server. SQLite memory, yt-dlp cache, and local
music use visible host directories by default, so they survive container
rebuilds and are easy to inspect or back up.

```bash
# Edit .env first (DISCORD_BOT_TOKEN, GEMINI_API_KEY, etc.)
docker compose up -d --build
```

The command above builds from the checked-out source. To deploy the published
image instead, run `docker compose pull` before `docker compose up -d`.

| Action | Command |
|---|---|
| View logs | `docker compose logs -f --tail=100` |
| Recreate (required after editing `.env`) | `docker compose up -d --force-recreate` |
| Stop | `docker compose down` |
| Update from the published image | `git pull && docker compose pull && docker compose up -d --force-recreate` |
| Rebuild the checked-out source | `git pull && docker compose up -d --build` |

The container uses Docker's isolated bridge network. Writable data is bind
mounted from `./data` and `./music_files` by default. Override the locations in
`.env` when storing data on another disk:

```env
APP_DATA_HOST_DIR=/srv/peacemusic/data
MUSIC_FILES_HOST_DIR=/srv/peacemusic/music
```

Before the first start, create the directories and assign them to the
unprivileged container user:

```bash
mkdir -p data music_files
docker compose run --rm --no-deps --user root --entrypoint sh peacemusic \
  -c 'chown -R peacemusic:peacemusic /app/data /app/music_files'
```

### Migrating from the previous named volumes

Before recreating an existing container, capture its current volume names:

```bash
CID=$(docker compose ps -aq peacemusic)
DATA_VOLUME=$(docker inspect "$CID" --format \
  '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Name}}{{end}}{{end}}')
MUSIC_VOLUME=$(docker inspect "$CID" --format \
  '{{range .Mounts}}{{if eq .Destination "/app/music_files"}}{{.Name}}{{end}}{{end}}')
```

Stop the bot, create the host directories, and use one-off containers to copy
the data. Keep the old volumes as a backup until the new deployment is verified:

```bash
docker compose stop peacemusic
mkdir -p data music_files

docker compose run --rm --no-deps --user root \
  -v "$DATA_VOLUME:/source:ro" --entrypoint sh peacemusic \
  -c 'cp -a /source/. /app/data/ && chown -R peacemusic:peacemusic /app/data'

docker compose run --rm --no-deps --user root \
  -v "$MUSIC_VOLUME:/source:ro" --entrypoint sh peacemusic \
  -c 'cp -a /source/. /app/music_files/ && chown -R peacemusic:peacemusic /app/music_files'

docker compose up -d --force-recreate peacemusic
```

### Host-side SOCKS proxy

On Linux, Compose maps `host.docker.internal` to Docker's host gateway. To use
an xray/SOCKS service running on the host, configure:

```env
GEMINI_SOCKS_PROXY=socks5://host.docker.internal:40000
```

The proxy must listen on the host gateway (or `0.0.0.0`), not only on
`127.0.0.1`. Restrict port 40000 to the Docker subnet with the host firewall;
do not expose an unauthenticated SOCKS proxy to the internet.

### Custom prompt in Docker

Compose mounts a host prompt read-only. The default is
`./utils/default_prompt.txt`; override it in `.env` without rebuilding:

```env
BOT_PROMPT_HOST_FILE=./prompt.txt
```

The file must exist before the container is created. After changing either its
path or contents, run `docker compose up -d --force-recreate`. This also works
when an editor replaces the file's inode, which a plain container restart does
not remount. Ensure the container user can read the host file (for example,
`chmod 644 prompt.txt`).

### yt-dlp cookies in Docker

Cookies are disabled by default. Keep the real file on the host and configure:

```env
YTDL_USE_COOKIES=true
YTDL_COOKIE_HOST_FILE=./data/cookies.txt
```

Compose mounts it read-only at `/app/config/cookies.txt`; it is not copied into
the image. The export must use Netscape format and start with
`# Netscape HTTP Cookie File` (the shorter `# HTTP Cookie File` header is also
accepted). Make it readable by the container user, for example with
`chmod 644 data/cookies.txt`. After changing the path or contents, recreate the
container with `docker compose up -d --force-recreate`.

---

## Configuration

All settings live in `.env` (see [`.env.example`](.env.example)).

### Required

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Discord bot token from the developer portal. |
| `GEMINI_API_KEY` | Google Gemini Developer API key. |

### Discord

| Variable | Default | Description |
|---|---|---|
| `CHATBOT_CHANNEL_ID` | *(mentions in any channel)* | Restrict AI chat to one channel. When empty, guild messages must mention the bot by default. |
| `DISCORD_STATUS_MESSAGE` | `PeaceMusic` | "Listening to …" status text. |

### Gemini

| Variable | Default | Description |
|---|---|---|
| `GEMINI_RESPONSE_MODEL` | `gemini-3.1-flash-lite` | Model used for chat replies. |
| `GEMINI_SUMMARY_MODEL` | `gemini-3.1-flash-lite` | Model used for background memory summarisation. |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | Model used to vectorise messages for semantic recall. |
| `GEMINI_EMBEDDING_DIMENSIONS` | `768` | Output dimensionality for embeddings. |
| `GEMINI_THINKING_BUDGET` | `8192` | Max tokens for Gemini's hidden reasoning per turn. |
| `GEMINI_TEMPERATURE` | `1.0` | Response sampling temperature. |
| `GEMINI_TOP_P` | `0.95` | Nucleus-sampling threshold. |
| `GEMINI_REQUEST_TIMEOUT_MS` | `24000` | Timeout for a Gemini SDK request, in milliseconds. |
| `GEMINI_SOCKS_PROXY` | *(off)* | In Docker bridge mode use `socks5://host.docker.internal:40000`. Applied to **all** Gemini SDK calls. |

`DISCORD_BOT_TOKEN_FILE` and `GEMINI_API_KEY_FILE` may be used instead of
putting those secrets directly in the environment.

### Paths and prompt

| Variable | Default | Description |
|---|---|---|
| `APP_DATA_HOST_DIR` | `./data` | Host directory bind-mounted at `/app/data` for SQLite memory and yt-dlp cache. |
| `MUSIC_FILES_HOST_DIR` | `./music_files` | Host directory bind-mounted at `/app/music_files`. |
| `BOT_PROMPT_FILE` | `utils/default_prompt.txt` | Prompt path for local Python runs. Compose sets the internal path automatically. |
| `BOT_PROMPT_HOST_FILE` | `./utils/default_prompt.txt` | Host prompt mounted read-only by Compose. |

### Memory

| Variable | Default | Description |
|---|---|---|
| `CHAT_MEMORY_DB` | `chat_memory.sqlite3` *(`/app/data/…` in Docker)* | SQLite database path. |
| `MEMORY_RECENT_MESSAGES` | `12` | Full recent messages replayed to the model. |
| `MEMORY_SEMANTIC_RESULTS` | `6` | Semantically relevant messages added to context. |
| `MEMORY_SEMANTIC_MIN_SCORE` | `0.35` | Minimum semantic similarity score. |
| `MEMORY_SUMMARY_TRIGGER` | `30` | Unsummarised messages that trigger a summary. |
| `MEMORY_SUMMARY_WINDOW` | `40` | Messages processed in one summary pass. |
| `MEMORY_SEMANTIC_HALF_LIFE_DAYS` | `30` | Age-decay half-life for semantic results; `0` disables decay. |
| `MEMORY_SEMANTIC_CANDIDATES` | `1000` | Maximum rows considered during semantic search. |
| `MEMORY_RAW_RETENTION_DAYS` | `90` | Summarised raw-message retention; `0` disables age pruning. |

### Music & yt‑dlp

| Variable | Default | Description |
|---|---|---|
| `MUSIC_DIRECTORY` | `music_files` | Where downloaded/cached tracks are written. |
| `YTDL_CACHE_DIR` | `data/ytdl_cache` | Persistent yt-dlp player/signature cache. |
| `YTDL_USE_COOKIES` | `false` | Enable cookies for `yt‑dlp`. |
| `YTDL_COOKIE_FILE` | `data/cookies.txt` | Netscape‑format cookies file for local Python runs. Compose sets the internal path automatically. |
| `YTDL_COOKIE_HOST_FILE` | *(off)* | Docker host file mounted at `/app/config/cookies.txt`; for example `./data/cookies.txt`. |
| `MUSIC_QUEUE_MAX_SIZE` | `50` | Maximum tracks in a guild queue. |
| `MUSIC_ATTACHMENT_MAX_BYTES` | `25000000` | Maximum downloaded music-attachment size. |
| `MEDIA_ALLOWED_DOMAINS` | YouTube and SoundCloud domains | Hosts accepted for remotely downloaded media. |
| `MUSIC_STREAM_BUFFER_SECONDS` | `20` | Maximum decoded PCM kept ahead of Discord playback (~192 KB per second per guild). |
| `MUSIC_STREAM_START_BUFFER_SECONDS` | `5` | Audio accumulated before playback starts. |
| `MUSIC_STREAM_START_TIMEOUT_SECONDS` | `15` | Maximum wait for the initial buffer. |
| `MUSIC_STREAM_UNDERRUN_GRACE_SECONDS` | `15` | Bounded silence while a depleted stream is being refreshed. |
| `MUSIC_STREAM_STALL_TIMEOUT_SECONDS` | `10` | Source inactivity before refreshing its signed media URL. |
| `MUSIC_STREAM_RESTART_COOLDOWN_SECONDS` | `10` | Minimum interval between stream refresh attempts. |
| `MUSIC_FFMPEG_RW_TIMEOUT_SECONDS` | `8` | FFmpeg network read/write timeout. |

### Rate limiting

| Variable | Default | Description |
|---|---|---|
| `AI_RATE_LIMIT_MAX_REQUESTS` | `20` | Max AI calls per user per window. `0` disables limiting. |
| `AI_RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding‑window size in seconds. |
| `AI_ATTACHMENT_MAX_BYTES` | `25000000` | Maximum size of one AI attachment. |
| `AI_ATTACHMENT_MAX_COUNT` | `4` | Maximum attachments processed per message. |
| `AI_MAX_CONCURRENT_TURNS` | `4` | Maximum AI turns processed concurrently. |
| `AI_TURN_TIMEOUT_SECONDS` | `120` | Overall timeout for one AI turn. |
| `AI_REQUIRE_MENTION_WHEN_UNSCOPED` | `true` | Require a mention in guilds when `CHATBOT_CHANNEL_ID` is empty. |

Throttled users get a `⏳` reaction instead of a reply.

---

## Usage

### Talk to the bot

Just send a message in the configured channel. The agent figures out what you want and calls the right tool:

> **You:** can you put on some lo‑fi and crank it a little
>
> **Bot:** 💭 *...*
>
> **Bot:** queued "Lofi Hip Hop Radio 📚 — beats to relax/study to" • volume set to 1.3

Natural‑language examples that all work:

- `play despacito`
- `play https://soundcloud.com/artist/track`
- `skip this one`, `skip the one with "remix" in the title`
- `seek to 1:23`
- `set volume to 50%`, `volume 1.5`
- `pause`, `resume`, `loop the track`, `loop the queue`, `stop looping`
- `shuffle the queue`, `clear queue`, `remove #3 from the queue`
- `what's playing?`, `show the queue`
- `come into my voice channel` / `disconnect`
- `react to that with 🔥`

You can also attach **images or short videos** and ask the bot about them, or drop an **audio file** to have it played straight into voice.

### Slash commands

| Command | Permissions | Description |
|---|---|---|
| `/bot_access action:<Disable\|Enable\|Status> member:<user>` | *Manage Server* / Administrator | Block or unblock a specific member from interacting with the AI in text chat. |
| `/bot_speech action:<Mute\|Unmute\|Status>` | *Manage Messages* | Enable or disable silent mode for the current channel. When muted, the bot will not respond to messages. |

---

## Memory System

PeaceMusic keeps Gemini coherent across long conversations with a four‑layer memory built on SQLite:

| Level | Source | Purpose |
|---|---|---|
| **L0 — Global summary** | Background Gemini call after every *N* messages | Rolling compressed summary: vibe, people, projects, running jokes. Capped ~1200 chars. |
| **L1 — Semantic recall** | Cosine similarity against per‑message embeddings, weighted by **temporal half‑life decay** | Surfaces relevant older messages even if they fall out of the recent window. |
| **L1.5 — Temporal context** | Last *N* messages serialised as structured metadata | Helps the model understand who said what when, without polluting role alternation. |
| **L2 — Recent turns** | Last *N* full message contents, replayed as proper `user`/`model` content | The immediate chat history. |

Tool calls and their results are persisted too, so the model can "remember" that it already searched for a track or that a previous skip failed. Raw rows older than `MEMORY_RAW_RETENTION_DAYS` are pruned once they've been folded into the global summary, keeping the DB small.

---

## Project Structure

```
PeaceMusic/
├── main.py                  # Entry point — wires up cogs, signal handlers, uvloop
├── config.py                # Typed settings, .env loader, FFmpeg/yt‑dlp tuning
├── cogs/
│   ├── ai_cog.py            # Thin re‑export of the chat cog
│   ├── ai/
│   │   ├── cog.py           # GeminiChatCog: on_message pipeline, tool dispatch
│   │   ├── response.py      # ResponseGenerator: Gemini call loop with tool round‑trips
│   │   ├── memory.py        # MemoryStore: SQLite schema, semantic recall, summary state
│   │   ├── embeddings.py    # GeminiEmbeddingService
│   │   └── attachments.py   # Image/video → Gemini Files API
│   └── music_cog.py         # Music cog: yt‑dlp, queue, voice client, all tool handlers
├── utils/
│   ├── tools.py             # Gemini Tool Calling schema (play, skip, seek, think, …)
│   ├── default_prompt.txt   # System prompt
│   └── default_prompt_example.txt
├── tests/                   # pytest suite (config, memory, embeddings, attachments, …)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Development

```bash
# Run the test suite
pytest

# Lint / format
black .
flake8
```

CI is wired up in [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

### Updating

```bash
git pull
pip install -r requirements.txt
# Docker:  docker compose up -d --build
```

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ffmpeg was not found` | Install FFmpeg and make sure it's on `PATH`. On Debian/Ubuntu: `sudo apt install ffmpeg`. |
| `No supported JavaScript runtime` from `yt-dlp` | Rebuild the current Docker image with `docker compose up -d --build`; for local installs, add **Deno 2.3+** (recommended) or **Node.js 22+**. |
| YouTube playback fails with signature errors | Update `yt-dlp` and `yt-dlp-ejs` together, ensure a supported JS runtime is installed, then restart the bot. |
| `403`/`age-restricted` from YouTube | Set `YTDL_USE_COOKIES=true`; in Docker also set `YTDL_COOKIE_HOST_FILE=./data/cookies.txt`, then recreate the container. |
| `GEMINI_SOCKS_PROXY requires httpx[socks]` | Re‑install dependencies: `pip install -r requirements.txt`. |
| Bot connects but does not respond to messages | Check `CHATBOT_CHANNEL_ID`, the bot's channel permissions, and that **Message Content Intent** is enabled in the developer portal. |
| Memory DB growing too large | Lower `MEMORY_RAW_RETENTION_DAYS` in `.env`, then recreate/restart the bot. Back up the database before deleting it manually. |
| Voice connection drops after a few seconds | Verify `PyNaCl` installed and the bot has the `Connect` + `Speak` permissions in the voice channel. |

---

## License

Released under the MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

Built with <a href="https://github.com/Rapptz/discord.py">discord.py</a>, <a href="https://ai.google.dev/">Google Gemini</a>, <a href="https://github.com/yt-dlp/yt-dlp">yt‑dlp</a>, and <a href="https://ffmpeg.org/">FFmpeg</a>.

</div>
