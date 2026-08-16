<div align="center">

# 🎵 PeaceMusic v2

### A production-ready Discord music player with a persistent Gemini AI assistant

<p>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+"></a>
  <a href="https://discord.com/developers/docs/intro"><img src="https://img.shields.io/badge/Discord-discord.py-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="discord.py"></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL-16%2B-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL 16+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-see%20LICENSE-111827?style=for-the-badge" alt="License"></a>
</p>

<p>
  <strong>Music owned by PeaceMusic.</strong><br>
  <code>discord.py</code> · <code>yt-dlp</code> · <code>FFmpeg</code> · <code>LangGraph</code> · <code>Gemini</code> · <code>PostgreSQL</code>
</p>

</div>

PeaceMusic is a multi-guild Discord music and AI assistant built for reliable
operation, clear boundaries, and configuration from Discord. It combines
first-party voice playback with persistent playlists, playback history,
LangChain/LangGraph agent workflows, multimodal Gemini input, and PostgreSQL-
backed memory.

> **No Lavalink.** PeaceMusic owns the playback stack with `discord.py`,
> `yt-dlp`, and FFmpeg.

<div align="center">

| 🎶 Music | 🤖 AI | 🧠 Memory | 🛡️ Operations |
|:---:|:---:|:---:|:---:|
| Queues, playlists, autoplay, voice | Gemini tools and LangGraph | Persistent semantic memory | Docker, health, metrics, CI |

</div>

## ✨ Contents

<details open>
<summary>Explore the documentation</summary>

- [Highlights](#highlights)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Discord application setup](#discord-application-setup)
- [Configuration](#configuration)
- [Local development](#local-development)
- [Docker Compose deployment](#docker-compose-deployment)
- [Discord commands](#discord-commands)
- [Persistence and migrations](#persistence-and-migrations)
- [Migrating from v1](#migrating-from-v1)
- [Operations](#operations)
- [Testing and quality](#testing-and-quality)
- [Project layout](#project-layout)
- [Security model](#security-model)
- [Troubleshooting](#troubleshooting)
- [License](#license)

</details>

## 🚀 Quick start

```bash
cp .env.example .env
# Set DISCORD_BOT_TOKEN, GEMINI_API_KEY, and DATABASE_URL in .env
uv sync --group dev
uv run alembic upgrade head
uv run peacemusic-v2
```

For the full production stack:

```bash
docker compose up --build -d
```

## ✨ Highlights

### 🎶 Music

- YouTube and other supported media sources through an isolated `yt-dlp`
  resolver.
- FFmpeg-based Discord voice playback with reconnect behavior and bounded
  retries.
- Per-guild players, queues, volume, seek, loop modes, autoplay, and idle
  disconnect handling.
- Persistent playlists and playback history in PostgreSQL.
- Persistent player messages with interactive controls.
- Direct playback of trusted Discord audio attachments.
- DJ-role and capability-aware authorization for live-player operations.

### 🤖 AI and memory

- Gemini through LangChain's `create_agent` interface.
- A compiled outer LangGraph `StateGraph` for deterministic normalization,
  policy, routing, and finalization around the model/tool subgraph.
- Persistent LangGraph PostgreSQL checkpoints using stable guild/channel
  thread identifiers.
- Persistent LangGraph Store-backed semantic memory with user, channel, and
  guild namespaces.
- Bounded short-term conversation history with token-aware compaction.
- Music and memory tools that call application services instead of Discord
  command implementations.
- Per-user rate limits, bounded model/tool recursion, turn timeouts, and
  cancellation handling.
- Secure multimodal attachment validation, temporary download handling, Gemini
  Files upload, and persistent media references in conversation context.

### ⚙️ Guild administration

- `/setup` interactive seven-step onboarding wizard.
- `/settings` interactive guild configuration center.
- PostgreSQL-backed settings with validation, global safety ceilings, caching,
  invalidation, and audit events.
- Configurable music and AI channels, mention behavior, autoplay, volume,
  voice behavior, memory features, and operator-controlled AI model allowlists.
- Persistent blocked-user and silent-channel controls.

### 🛡️ Production readiness

- PostgreSQL and Alembic migrations.
- Structured application logging and in-process metrics.
- `/health/live`, `/health/ready`, and `/metrics` HTTP endpoints.
- Supervised background tasks and orderly shutdown.
- Non-root Docker image with FFmpeg, Deno, locked dependencies, resource
  limits, persistent caches, and Compose health checks.
- CI checks for formatting, linting, tests, PostgreSQL integration, migrations,
  and Docker builds.

## 🧭 Architecture

The repository uses explicit dependency boundaries and a single composition
root:

```text
Discord commands, views, events
              │
              ▼
       Application services
       ┌──────┼─────────┐
       ▼      ▼         ▼
   Music   Settings   Agent
       │      │         │
       ▼      ▼         ▼
  Player   PostgreSQL  LangGraph
       │                │
       ▼                ▼
  FFmpeg            LangChain + Gemini
       ▲
       │
    yt-dlp
```

Discord Cogs are adapters. Business rules live in application modules, and
external systems are isolated behind ports and infrastructure adapters.

Important boundaries include:

- `MusicService` owns playback operations shared by slash commands, player
  buttons, playlists, and AI tools.
- `GuildSettingsService` is the access point for effective guild behavior;
  settings views do not issue SQL directly.
- `AgentService` coordinates rate limits, conversation context, attachments,
  tool availability, persistence, and provider execution.
- `LangGraphPersistence` owns the PostgreSQL checkpointer and Store lifecycle.
- `TaskSupervisor` owns application background tasks and shutdown cancellation.

## 📦 Requirements

For local development:

- Python 3.12 or newer.
- PostgreSQL 16 or newer.
- FFmpeg available on `PATH` for local voice playback.
- A Discord application and bot token.
- A Google Gemini API key for AI features.
- [`uv`](https://docs.astral.sh/uv/) for reproducible dependency management.

For the recommended deployment, Docker Engine and Docker Compose are enough;
the image includes Python dependencies, FFmpeg, and Deno. Compose also starts
PostgreSQL and the `bgutil-provider` service used by the media environment.

## 🔗 Discord application setup

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create a bot user and copy its token into `DISCORD_BOT_TOKEN`.
3. Enable the following privileged intents for the bot:
   - Message Content Intent
   - Server Members Intent
4. Invite the bot with the `bot` and `applications.commands` OAuth scopes.
5. Grant the bot at least these permissions:
   - View Channels
   - Send Messages
   - Embed Links
   - Add Reactions
   - Read Message History
   - Connect
   - Speak
6. Invite the bot to a test guild and run `/setup` as a user with Manage
   Server permission.

The bot disables allowed mentions globally and does not expose infrastructure
secrets through Discord.

## 🔧 Configuration

Infrastructure configuration is loaded from `.env` by Pydantic Settings. Guild
behavior belongs in PostgreSQL and is changed through `/setup` and `/settings`.

Create a local environment file:

```bash
cp .env.example .env
```

At minimum, set:

```dotenv
DISCORD_BOT_TOKEN=your-discord-bot-token
GEMINI_API_KEY=your-gemini-api-key
DATABASE_URL=postgresql://peacemusic:change-me@localhost:5432/peacemusic
```

`GOOGLE_API_KEY` is accepted as an alias for `GEMINI_API_KEY`, and
`DISCORD_BOT_TOKEN` is the canonical Discord token name.

### Bootstrap settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | required | Discord bot credential. |
| `DISCORD_APPLICATION_ID` | unset | Optional Discord application ID. |
| `DATABASE_URL` | `postgresql://peacemusic:peacemusic@localhost:5432/peacemusic` | PostgreSQL connection URL. |
| `DB_MIN_POOL_SIZE` | `1` | Minimum PostgreSQL pool size. |
| `DB_MAX_POOL_SIZE` | `10` | Maximum PostgreSQL pool size. |
| `GEMINI_API_KEY` | required | Gemini API credential. |
| `GEMINI_RESPONSE_MODEL` | `gemini-3.1-flash-lite` | Default response model. |
| `GEMINI_SYSTEM_PROMPT` | built-in PeaceMusic prompt | Default personality for newly created guild settings. |
| `ALLOWED_AI_MODELS` | ["gemini-3.1-flash-lite"] | Operator allowlist for guild-selectable models. |
| `GEMINI_REQUEST_TIMEOUT_SECONDS` | `30` | Provider request timeout. |
| `LOG_LEVEL` | `INFO` | Application log level. |
| `ENVIRONMENT` | `development` | Logging/deployment environment. |
| `LANGSMITH_TRACING` | `false` | Optional LangSmith tracing switch. |
| `LANGSMITH_API_KEY` | unset | Optional LangSmith credential. |

### Global safety limits

These limits are operator-controlled and cannot be exceeded by a guild:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `GLOBAL_MAX_CONCURRENT_AI_TURNS` | `20` | Maximum simultaneous AI turns. |
| `GLOBAL_MAX_DOWNLOAD_SIZE_MB` | `100` | Maximum attachment/download size. |
| `GLOBAL_MAX_QUEUE_SIZE` | `1000` | Maximum guild queue size. |
| `HEALTH_SERVER_PORT` | `8080` | Internal HTTP health/metrics port. |

`ALLOWED_AI_MODELS` should be supplied as a JSON-style list, for example:

```dotenv
ALLOWED_AI_MODELS=["gemini-3.1-flash-lite"]
```

yt-dlp cookies are optional. Set `YTDL_COOKIES_FILE` in `.env` to a Netscape
format cookies file, preferably under `./data`, for example:

```env
YTDL_COOKIES_FILE=./data/youtube-cookies.txt
```

The `data` directory is already mounted into the Docker container at
`/app/data`, so this same relative path works both from the repository root
without Docker and inside Docker. Keep the file private, do not commit it, and
use a dedicated account when possible.

## 💻 Local development

### Install dependencies

From the repository root:

```bash
uv sync --group dev
cp .env.example .env
```

Start PostgreSQL locally, set `DATABASE_URL`, then apply the schema:

```bash
uv run alembic upgrade head
```

Start PeaceMusic:

```bash
uv run peacemusic-v2
```

The equivalent module entrypoint is:

```bash
uv run python -m peacemusic.main
```

### Local health endpoints

The health server listens on `0.0.0.0:8080` by default. When running the bot
directly, the endpoints are:

```text
GET /health/live   Process liveness; returns HTTP 200 while the server runs.
GET /health/ready  PostgreSQL and Discord readiness; returns HTTP 503 otherwise.
GET /metrics       Plain-text application metrics.
```

## 🐳 Docker Compose deployment

Docker Compose is the recommended production starting point.

1. Create and edit `.env`:

   ```bash
   cp .env.example .env
   ```

   Set `DISCORD_BOT_TOKEN`, `GEMINI_API_KEY`, and a strong
   `POSTGRES_PASSWORD`. Compose constructs the internal PostgreSQL URL for the
   application from `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.

2. Start the stack:

   ```bash
   docker compose up --build -d
   ```

3. Follow application logs:

   ```bash
   docker compose logs -f peacemusic
   ```

4. Stop the stack without deleting data:

   ```bash
   docker compose down
   ```

The application container runs `alembic upgrade head` before starting the bot.
The stack contains:

| Service | Role |
| --- | --- |
| `peacemusic` | Discord bot, health server, music, AI, and application services. |
| `postgres` | PostgreSQL 16 persistent database. |
| `bgutil-provider` | yt-dlp challenge/provider helper. |

Compose persists:

- PostgreSQL data in the `postgres_data` named volume.
- yt-dlp cache in the `ytdlp_cache` named volume.
- application data under `APP_DATA_HOST_DIR`, defaulting to `./data`.
- music files under `MUSIC_FILES_HOST_DIR`, defaulting to `./music_files`.

The health port is internal by default. To expose it to the host, add a local
Compose override or edit the service ports:

```yaml
services:
  peacemusic:
    ports:
      - "8080:8080"
```

The image runs as a non-root user, drops Linux capabilities, enables
`no-new-privileges`, uses bounded CPU/memory/process settings, and configures
container log rotation.

## 🎛️ Discord commands

All guild commands require a guild context. Administrative commands require
Manage Server unless noted otherwise.

### Setup and settings

| Command | Description |
| --- | --- |
| `/setup` | Run the initial seven-step guild setup wizard. |
| `/settings` | Open the interactive settings panel. |
| `/memory clear-history` | Delete this channel's short-term AI conversation history and reset its LangGraph thread. |
| `/dj add <role_id>` | Add a DJ role. |
| `/dj remove <role_id>` | Remove a DJ role. |
| `/dj list` | List configured DJ roles. |

The `/settings` panel lets a Manage Server administrator select a section and
edit every persisted guild option through Discord. It covers General, Music,
Voice, AI, and Memory settings, including channels, volumes, queue limits,
autoplay, voice timeouts, model selection, tool permissions, reactions,
memory behavior, and the per-server system prompt. Values are converted and
validated before being written to PostgreSQL, and invalid values or values
outside operator safety limits are rejected with an ephemeral error.

Music queue announcements are rich embeds with the track title, source link,
thumbnail, uploader, duration, requester, and queue position. They are sent
for slash commands, AI music tools, playlists, and autoplay; the Music
`track_announce` option and General `notifications_enabled` option control
whether they are visible for a guild.

Discord channel fields accept a channel ID; leave an optional channel field
blank to clear it. Boolean fields accept `true`/`false` (also `yes`/`no` or
`on`/`off`), and loop mode accepts `off`, `track`, or `queue`. The panel is
intentionally limited to guild behavior: bot tokens, API keys, database
URLs, global safety ceilings, and other infrastructure settings remain in
`.env` and are not exposed to guild administrators.

`GEMINI_SYSTEM_PROMPT` controls the operator default for guilds that do not
yet have saved settings; it does not overwrite an existing guild's custom
personality.

The setup wizard configures the music channel, AI channel, AI enablement,
mention mode, DJ role, default volume, and autoplay. The settings panel groups
controls into General, Music, Voice, AI, and Memory sections.

### Music

| Command | Description |
| --- | --- |
| `/play <query>` | Resolve and queue a track. |
| `/search <query>` | Resolve a playable track without queueing it. |
| `/pause` | Pause playback. |
| `/resume` | Resume playback. |
| `/skip` | Skip the current track. |
| `/stop` | Stop playback and clear the queue. |
| `/seek <seconds>` | Seek within the current track. |
| `/volume <value>` | Set the current player volume. |
| `/join` | Join the caller's voice channel. |
| `/leave` | Disconnect from voice. |
| `/queue` | Show the current queue. |
| `/remove <index>` | Remove a queued track. |
| `/move <source_index> <target_index>` | Move a queued track. |
| `/shuffle` | Shuffle the queue. |
| `/clear` | Clear queued tracks. |
| `/loop <off\|track\|queue>` | Select the loop mode. |
| `/nowplaying` | Show or update the persistent player message. |
| `/autoplay <enabled>` | Change the guild autoplay setting. |
| `/history [limit]` | Show recently played tracks. |

The persistent player message also exposes controls for common playback
operations. Buttons call `MusicService` directly, just like slash commands and
AI music tools.

### Playlists

| Command | Description |
| --- | --- |
| `/playlist create <name>` | Create a personal guild playlist. |
| `/playlist delete <name>` | Delete a playlist. |
| `/playlist add <name> <query>` | Resolve and add a track reference. |
| `/playlist remove <name> <index>` | Remove a track reference. |
| `/playlist play <name>` | Queue a saved playlist. |
| `/playlist list` | List the caller's playlists. |

Playlists store track metadata and source references, not permanently downloaded
audio files.

### Memory and access control

| Command | Description |
| --- | --- |
| `/memory status` | Show memory state and the caller's record count. |
| `/memory stats` | Show the caller's memory statistics. |
| `/memory forget <memory_id>` | Delete one caller-owned memory. |
| `/memory clear-channel <channel_id>` | Clear channel memory; admin-only. |
| `/memory clear-user <user_id>` | Clear a user's memory; admin-only. |
| `/access block-user <user_id>` | Block a user from bot responses. |
| `/access unblock-user <user_id>` | Remove a user block. |
| `/access silence-channel <channel_id>` | Silence bot responses in a channel. |
| `/access unsilence-channel <channel_id>` | Remove channel silent mode. |

The AI agent can use `remember`, `recall`, and `forget` tools when the relevant
guild settings allow them. All side effects are authorized by application code;
the model cannot grant itself permissions.

## 🗄️ Persistence and migrations

PostgreSQL is the system of record for guild behavior and application state.
The migration chain currently owns:

- guild settings, roles, and permissions;
- blocked users and silent channels;
- playlists and playlist tracks;
- playback history;
- audit events;
- long-term memory records;
- bounded conversation messages;
- persistent player message identities.

Inspect migration state:

```bash
uv run alembic current
```

Apply all migrations:

```bash
uv run alembic upgrade head
```

Create a new migration during development:

```bash
uv run alembic revision -m "describe the change"
```

Production startup applies pending migrations automatically in the Docker
image. For controlled deployments, migrations can be run as a separate release
step before starting the bot.

## 🔄 Migrating from v1

The repository includes `scripts/migrate_v1_sqlite.py` for importing supported
data from a v1 SQLite database.

The importer handles:

- safe guild settings that exist in the v2 schema;
- disabled users;
- muted/silent channels;
- explicit text memories.

It intentionally does not import raw conversation transcripts or legacy
embedding BLOBs. Imported text memories are written into the v2 memory store so
their embeddings can be recomputed by the current provider integration.

Always perform a dry run first:

```bash
uv run python scripts/migrate_v1_sqlite.py ./old.sqlite3 \
  --database-url "$DATABASE_URL" \
  --dry-run
```

Run the import after reviewing the summary:

```bash
uv run python scripts/migrate_v1_sqlite.py ./old.sqlite3 \
  --database-url "$DATABASE_URL"
```

The importer uses deterministic IDs for imported text memories, making repeated
runs safe for the same namespace/content pair.

## 📈 Operations

### Readiness and metrics

Use `/health/live` for container liveness probes. Use `/health/ready` for load
balancers or orchestration readiness checks; readiness requires the application
to be initialized, PostgreSQL to respond, and the Discord bot to be ready.
Gemini availability is not required for readiness, so a temporary AI outage
does not unnecessarily restart the music bot.

Metrics are available at `/metrics` and include agent turns, LLM requests,
tool calls, yt-dlp operations, queue size, stream restarts, buffer underruns,
settings updates, and memory operations. High-cardinality guild, channel, and
user identifiers are not used as metric labels.

### Shutdown

SIGTERM and SIGINT trigger an orderly shutdown. Active resources are closed in
the application lifecycle, including supervised tasks, players, voice
connections, LangGraph persistence, health server, Discord, and PostgreSQL.

### Backups

Back up PostgreSQL using your normal PostgreSQL tooling. The named
`postgres_data` volume is the source of persistent guild configuration,
playlists, history, audit records, and database-owned memory. The yt-dlp cache is
rebuildable and must not be treated as application state.

## ✅ Testing and quality

Install development dependencies with `uv sync --group dev`, then run:

```bash
uv run black --check src scripts tests
uv run flake8 src scripts tests
uv run pytest --cov=src/peacemusic --cov-report=term-missing \
  --cov-fail-under=80 -q
```

Integration tests are marked separately and use a real PostgreSQL instance:

```bash
export DATABASE_URL=postgresql://peacemusic:peacemusic@localhost:5432/peacemusic
uv run alembic upgrade head
uv run pytest -m integration -q
```

Without `DATABASE_URL`, PostgreSQL integration tests are skipped. Unit and
adapter-boundary tests do not require YouTube, Discord voice, FFmpeg, or a
running Gemini service.

Build and validate the production artifacts locally:

```bash
docker build --tag peacemusic:local .
docker compose config --quiet
```

CI also verifies the locked dependency graph, PostgreSQL migrations, LangGraph
Store restart persistence, and the production image build.

## 🗂️ Project layout

```text
.
├── src/peacemusic/
│   ├── adapters/discord/       Discord bot, Cogs, views, presenters, voice
│   ├── bootstrap/              Composition root and lifecycle
│   ├── core/                   Configuration, errors, logging, metrics, tasks
│   ├── infrastructure/        PostgreSQL, media, FFmpeg, health, LLM adapters
│   └── modules/                Agent, access, audit, memory, music, playlists,
│                               settings, history, and autoplay
├── migrations/                 Alembic environment and revisions
├── scripts/                    Operational utilities, including v1 migration
├── tests/                      Unit, adapter, and PostgreSQL integration tests
├── Dockerfile                  Locked non-root production image
├── docker-compose.yml          Bot, PostgreSQL, and media-provider stack
├── pyproject.toml              Project and dependency configuration
├── uv.lock                     Reproducible dependency lockfile
├── .env.example                Environment variable template
└── LICENSE
```

## 🔒 Security model

- Secrets are loaded at process startup and are not editable or displayable
  through Discord.
- Guild administrators can change only guild-scoped settings exposed by the
  application service.
- AI model selection is restricted to an operator-controlled allowlist.
- Music, memory, settings, playlist, and access-control side effects are
  authorized in Python application services.
- Attachments are validated by count, MIME type, and size before provider use;
  local temporary files are cleaned up after each request, while successful
  Gemini media references may remain available for subsequent conversation turns.
- External media URLs use explicit trusted-domain policies where applicable.
- LangGraph checkpoint state contains serializable values only; Discord objects,
  database connections, locks, subprocesses, and clients are never persisted.
- Docker runs as a non-root user with dropped capabilities and
  `no-new-privileges`.
- Tool and model execution is bounded by rate limits, concurrency limits,
  recursion limits, timeouts, queue limits, and download limits.

## 🧰 Troubleshooting

### Slash commands are not visible

Confirm that the bot was invited with the `applications.commands` scope and
that it has connected successfully. Command synchronization occurs during bot
startup; global Discord command propagation can take some time.

### The bot starts but AI does not respond

Check `GEMINI_API_KEY` or `GOOGLE_API_KEY`, the selected model's presence in
`ALLOWED_AI_MODELS`, and the guild's AI/channel/mention settings in
`/settings`. A blocked user or silent channel is intentionally ignored.

### Music cannot start

For local execution, verify that `ffmpeg` and `yt-dlp` are installed and that
the bot has Connect and Speak permissions. For Compose, inspect both
`peacemusic` and `bgutil-provider` logs:

```bash
docker compose logs --tail=200 peacemusic bgutil-provider
```

### PostgreSQL connection or migration errors

Verify `DATABASE_URL`, database credentials, and PostgreSQL readiness. In
Compose, the application uses the internal `postgres` hostname and waits for
the database health check before starting. To inspect the migration state:

```bash
docker compose exec peacemusic alembic current
```

### Health endpoint is unreachable from the host

The health server listens inside the container by default. Add a
`8080:8080` port mapping as shown in the Docker section, or query it from
inside the Compose network.

## 📄 License

PeaceMusic is distributed under the terms in [`LICENSE`](LICENSE).
