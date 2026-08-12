# PeaceMusic v2 — Architecture and Technology Stack

## Purpose and scope

This document describes the architecture that is present in the repository today. It is based on the implementation under `src/peacemusic`, the migrations, tests, deployment files, CI workflow, and package configuration. It does not describe an earlier specification or an intended future design.

PeaceMusic is an asynchronous Discord music bot with optional AI assistance. It combines Discord interaction handling, guild-scoped settings and permissions, music playback, playlists and history, multimodal AI requests, memory, PostgreSQL persistence, and containerized production operation.

The central architectural decision is to keep Discord and third-party provider details at the edges of the application. Application services and domain models express the important behavior; adapters translate between those services and Discord, PostgreSQL, Google AI, yt-dlp, FFmpeg, and LangGraph.

## Executive summary

At runtime, `peacemusic.main` builds an explicit dependency graph through `bootstrap.container.build_container`. The container starts the database, optional LangGraph persistence, and the health server before the Discord bot is started. The bot is the Discord adapter: its cogs translate slash commands and messages into application-service calls, while presenters and views translate results back into Discord responses and persistent controls.

The application is organized around capability modules rather than one large bot class:

- `modules/music` owns queues, per-guild player state, playback policy, and music operations.
- `modules/settings` owns the validated guild-settings aggregate, defaults, caching, authorization, and auditing.
- `modules/agent` owns AI request orchestration, policy checks, tool exposure, conversation coordination, and provider-independent request state.
- `modules/memory`, `modules/playlists`, `modules/history`, `modules/access`, `modules/audit`, and `modules/autoplay` isolate other business capabilities.
- `infrastructure` contains concrete integrations and persistence implementations.
- `adapters/discord` contains Discord-specific cogs, permissions, voice integration, views, presenters, and request-context creation.
- `core` provides cross-cutting configuration, logging, metrics, and task supervision.

The design is deliberately asynchronous. Discord events, database access, HTTP downloads, AI calls, and playback coordination all run in an async application. Blocking provider SDK calls and yt-dlp extraction are moved to worker threads and guarded by timeouts or concurrency limits.

## System context

```text
                       Discord users and guilds
                                |
                                v
                         discord.py Bot
                  commands, events, views, voice
                                |
                                v
                    Discord adapter / cogs / presenters
                                |
                                v
             Application services and capability modules
              |              |                |
              v              v                v
       Music and voice     AI workflow       Settings/policy
              |              |                |
              v              v                v
       yt-dlp + FFmpeg  Gemini + LangChain  PostgreSQL repositories
                              |
                              v
                    LangGraph checkpoints/store
```

The process also exposes operational endpoints independently of Discord:

```text
HTTP client / orchestrator --> aiohttp HealthServer
                              |-- /health/live
                              |-- /health/ready
                              `-- /metrics
```

## Technology stack

The following table lists technologies that are declared and used by the current implementation. Paths identify where the integration is visible in the repository.

| Technology | Where it is used | Problem it solves | Why it fits this project |
| --- | --- | --- | --- |
| Python 3.12 | `pyproject.toml`, Docker image, CI | Application implementation language | It has mature Discord, async I/O, database, media, and AI libraries, while remaining productive for a small service with many integrations. |
| `discord.py` 2.x | `adapters/discord`, `main.py` | Discord gateway events, slash commands, persistent views, and voice connection | It provides the event-driven Discord API needed by the bot and lets the adapter stay focused on translating Discord concepts into application requests. |
| `asyncio` | All services and adapters | Coordination of concurrent I/O, playback, timeouts, locks, and shutdown | The bot is I/O-heavy. A single async process can coordinate Discord, PostgreSQL, HTTP, AI, and media work without a thread per operation. |
| Pydantic 2 | Domain/settings models and contracts | Validation and serialization of settings, requests, tool results, attachments, and checkpoint-safe state | Configuration and AI/tool boundaries benefit from explicit validation. Invalid settings fail at the boundary instead of propagating as loosely typed dictionaries. |
| `pydantic-settings` | `core/config.py` | Environment-based configuration | Deployment configuration stays outside the image and is parsed into typed settings, including nested AI, database, Discord, and voice options. |
| PostgreSQL 16 | `docker-compose.yml`, repositories, integration tests | Durable guild data, settings, audit events, history, playlists, conversation messages, and identities | The bot needs transactional, multi-guild persistent state. PostgreSQL handles concurrent service instances and structured JSONB data better than local SQLite files. |
| `asyncpg` | `infrastructure/persistence/database.py` and PostgreSQL repositories | Fast asynchronous SQL access and connection pooling | It matches the async application model and gives repositories direct, predictable SQL behavior. |
| `psycopg` 3 | `infrastructure/llm/langgraph_persistence.py` | PostgreSQL driver required by LangGraph’s async checkpointer/store | LangGraph persistence uses its own PostgreSQL integration, so the application converts the asyncpg URL into the driver format expected by that library. |
| Alembic | `migrations`, `alembic.ini`, container command | Versioned schema evolution | Schema changes are repeatable in CI and production through `alembic upgrade head`, rather than being implicit application side effects. |
| LangChain | `infrastructure/llm/langchain_agent.py`, agent tool adapters | Provider-facing agent creation and tool protocol | It provides the model/tool invocation abstraction while the application keeps business operations in its own services. |
| LangChain Google GenAI | `LangChainAgentFactory` | Gemini chat-model integration for agent turns | The application uses Gemini as its model provider while keeping provider construction behind one infrastructure factory. |
| LangGraph | `modules/agent/workflow.py` | Explicit stateful workflow and checkpoint-compatible agent request state | A graph gives the agent request a visible lifecycle and a stable state object, which is more inspectable than hiding all orchestration in a single callback. |
| `langgraph-checkpoint-postgres` | `infrastructure/llm/langgraph_persistence.py` and `LangGraphMemoryRepository` | Durable agent checkpoints and semantic memory storage | Conversation/thread state and long-term memory can survive process restarts while remaining backed by PostgreSQL. |
| Google GenAI SDK | `infrastructure/llm/gemini_files.py`, `embeddings.py` | Gemini file uploads and embeddings | The SDK supplies capabilities not handled by the chat-model wrapper, especially multimodal file references and vector embeddings. |
| `yt-dlp` | `infrastructure/media/ytdlp.py` | Resolve search queries and supported provider URLs to playable media metadata/streams | It supports the media providers required by the bot and is isolated behind `MediaResolver`, making the rest of the application independent of extraction details. |
| FFmpeg | `infrastructure/media/ffmpeg.py`, Dockerfile | Convert resolved media into Discord-compatible PCM audio | FFmpeg is the established bridge between provider streams and Discord voice playback. |
| `aiohttp` | `infrastructure/health/server.py` | Lightweight health and Prometheus endpoint server | Health probes must be available even when no Discord command is being processed. |
| `httpx` | `infrastructure/attachments/downloader.py` | Bounded, asynchronous attachment downloads | It supports redirect policy and request timeouts needed when users provide external Discord attachment URLs. |
| `uv` | `pyproject.toml`, `uv.lock`, Dockerfile, CI | Reproducible dependency resolution and installation | The lockfile lets local, CI, and container builds use the same resolved dependency graph. |
| Docker and Compose | `Dockerfile`, `docker-compose.yml` | Repeatable production packaging and local service orchestration | The application needs Python, FFmpeg, PostgreSQL, persistent volumes, resource limits, and a yt-dlp challenge-provider sidecar. |
| GitHub Actions | `.github/workflows/ci.yml` | Automated linting, tests, integration checks, and multi-architecture image publishing | The workflow makes repository quality and the production image build part of every branch/`main-v2` integration path. |
| pytest and pytest-cov | `tests`, `pyproject.toml`, CI | Unit, adapter, and PostgreSQL integration testing with coverage enforcement | Most boundaries can be tested with fakes, while the persistence layer receives a real PostgreSQL integration pass. |
| Black and Flake8 | `pyproject.toml`, CI | Consistent formatting and static lint checks | Automated style checks keep a multi-module Python service readable and reduce review noise. |

`requirements.txt` and `requirements-dev.txt` are also present as compatibility-oriented dependency lists. The current build and CI path is driven by `pyproject.toml` and the locked `uv.lock` file.

## Repository structure and boundaries

```text
src/peacemusic/
├── adapters/discord/       Discord-specific delivery and input adapters
├── bootstrap/              Composition root and application lifecycle
├── core/                   Configuration and cross-cutting runtime services
├── infrastructure/        Concrete providers, media, HTTP, health, and SQL adapters
└── modules/                Business capabilities and application services

migrations/                 Alembic environment and schema revisions
tests/                      Unit, adapter, and PostgreSQL integration tests
scripts/                    Operational migration utility
Dockerfile                  Multi-stage production image
docker-compose.yml          Local/production-shaped service topology
```

### Modules versus infrastructure

The `modules` packages contain behavior that should remain meaningful without Discord or a specific provider. For example, `MusicService` accepts a `MusicRequestContext` and ports such as `VoiceGateway`, `AudioSourceFactory`, and `MediaResolver`; it does not import yt-dlp or make Discord command responses.

The `infrastructure` packages implement those ports. `YtDlpMediaResolver` translates provider extraction into `ResolvedMedia`; `FFmpegAudioSourceFactory` translates a media URL into a Discord audio source; PostgreSQL repositories translate domain operations into SQL; and the Gemini adapters translate attachments and text into provider calls.

The separation is not absolute—Discord-specific composition is intentionally performed in `adapters/discord/bot.py`—but the application services do not need to know which Discord cog called them or which provider produced a stream.

### Explicit dependency injection

`bootstrap/container.py` is the composition root. `build_container()` constructs concrete repositories, services, provider adapters, and the health server, then passes dependencies into higher-level services. This has several practical effects:

1. Construction choices are visible in one place.
2. Unit tests can instantiate a service with fakes instead of booting Discord or PostgreSQL.
3. Provider changes are localized to an adapter and the composition root.
4. Startup and shutdown ownership is explicit.

The container is a runtime owner, not a service locator used throughout the application. Most services receive their dependencies through constructors and retain narrow interfaces.

## Application lifecycle

The lifecycle is coordinated by `peacemusic.main.run` and `ApplicationContainer`.

```text
main.run
  |
  | configure structured logging
  v
build_container
  |
  | parse environment configuration
  | create database, services, repositories, AI/media adapters
  v
create PeaceMusicV2Bot
  |
  | attach Discord voice gateway and FFmpeg source factory
  | register cogs and persistent PlayerView
  | register readiness callbacks
  v
container.start
  |
  | PostgreSQL pool connects
  | LangGraph checkpointer/store start and run setup, when configured
  | health server starts
  v
bot.start
  |
  | Discord becomes ready -> container.mark_discord_ready(True)
  v
running
  |
  | SIGTERM/SIGINT -> stop event
  v
orderly shutdown
  |
  | music idle tasks cancel
  | supervised tasks shut down
  | health server stops
  | LangGraph persistence stops
  | database pool closes
```

Readiness is intentionally stricter than liveness. `/health/live` reports that the process can answer HTTP requests. `/health/ready` reports ready only when Discord has reached `on_ready` and the database health check (`SELECT 1`) succeeds. Discord disconnects therefore make readiness false without confusing a live process with a ready service.

## Discord adapter architecture

`PeaceMusicV2Bot` subclasses `commands.Bot`, but it is primarily a wiring and event boundary. It configures mention-only command behavior, disables unwanted allowed mentions, installs the Discord settings authorizer, registers cogs, and synchronizes the application command tree.

The cogs map Discord interactions to application capabilities:

| Adapter | Responsibility |
| --- | --- |
| `SettingsCog` | Expose validated guild settings and update operations. |
| `MusicCog` | Handle playback commands and player interactions. |
| `PlaylistCog` | Translate playlist commands to the playlist service when enabled. |
| `MemoryCog` | Expose memory recall/forget operations. |
| `DJCog` | Manage configured DJ roles and related access. |
| `AccessCog` | Manage user/channel access controls. |
| `ChatCog` | Filter messages and route eligible AI requests to `AgentService`. |

The adapter deliberately keeps response presentation separate from business mutation. `presenters/music.py` and `presenters/settings.py` build user-facing Discord output; `views/player.py` and `views/settings.py` provide interactive controls. The persistent `PlayerView` is re-added when the bot starts, and player message identities are persisted by `PlayerMessageRepository`, allowing the UI to be associated with a guild/channel/message after restart.

### Message-to-agent path

`ChatCog.on_message` applies Discord-facing filters before invoking the application layer:

1. Ignore bot-authored messages and direct messages.
2. Suppress users or channels blocked by access policy.
3. Check that AI is enabled for the guild and, if configured, the current channel.
4. Enforce mention requirements when the guild requires them.
5. Build `AgentRequestContext`, including guild, channel, user, voice, role, and management information.
6. Convert attachments into `AttachmentRef` values.
7. Invoke `AgentService` inside Discord’s typing context.
8. Split responses into Discord’s 2,000-character message limit and add configured reactions.

The agent service does not receive a Discord `Message` object. It receives a serializable request context and application data, which makes the AI path easier to test and keeps Discord types at the adapter boundary.

## Music and playback architecture

Music playback has three layers:

```text
Discord command / PlayerView / AI music tool
                  |
                  v
             MusicService
                  |
       ┌──────────┼──────────┐
       v          v          v
 GuildPlayer   MediaResolver  PermissionService
       |          |
       v          v
 VoiceGateway  YtDlpMediaResolver
       |
       v
 FFmpegAudioSourceFactory -> discord.py voice client
```

### Domain and runtime state

`Track`, `ResolvedMedia`, `LoopMode`, and `PlaybackStatus` are framework-independent models. `TrackQueue` implements bounded queue operations and loop behavior. `GuildPlayer` stores the mutable runtime state for one guild: queue, current track, status, volume, position, and voice channel. `GuildPlayerManager` owns the per-guild player map and protects it with an async lock.

This state is intentionally in memory. Active voice playback is process-local and cannot be resumed meaningfully from a database after a process restart. Durable facts such as play history, audit events, playlists, and player message identity are persisted separately.

### MusicService as the application boundary

`MusicService` is used by slash commands, UI callbacks, and AI tools. It centralizes permission checks, voice-channel rules, resolution, queue mutation, history, audit, metrics, playback start, autoplay, and idle disconnect behavior. This prevents each delivery surface from implementing a subtly different version of “play” or “skip.”

The service depends on ports rather than concrete integrations. Its constructor accepts `MediaResolver`, `VoiceGateway`, and `AudioSourceFactory`, along with optional history, autoplay, recovery, settings, audit, and metrics services. Tests can therefore validate queue and playback policy with deterministic fakes.

### Provider and playback boundaries

`YtDlpMediaResolver` is an infrastructure adapter that:

- runs extraction in `asyncio.to_thread` because yt-dlp is blocking;
- bounds concurrent extraction with a semaphore;
- applies a timeout;
- disables playlist expansion and limits search results;
- validates supported domains;
- maps provider failures to application-level errors;
- records request, error, and duration metrics.

`FFmpegAudioSourceFactory` constructs `discord.FFmpegPCMAudio` with `-nostdin`, disables non-audio streams, applies an optional seek offset, and wraps the source in `discord.PCMVolumeTransformer`. It maps construction errors to `PlaybackError`, keeping FFmpeg details out of the application service.

The repository also contains `BufferedAudioSource`, a bounded, thread-safe PCM buffer with underrun metrics and silence fallback. It is a reusable infrastructure component, but the current composition path creates the FFmpeg source directly; the buffer is not currently inserted between FFmpeg and Discord voice playback. This is an important current-state distinction: the design contains a buffering option, but does not claim that every active playback path uses it.

### Playback safety and recovery

Playback completion callbacks are guarded with a playback token so an old callback cannot advance a newer track. `PlaybackRecoveryService` retries bounded playback failures, optionally refreshes a source, increments restart metrics, and raises a domain error after the configured attempt limit. When a queue becomes empty, `AutoplayService` consults guild settings and a provider callback, rejects an empty or duplicate result, and records autoplay history.

Idle disconnect is scheduled per guild when playback stops or the queue ends. Shutdown cancels those idle timers and the service’s playback-related tasks. The current implementation also creates a small number of playback and idle tasks directly with `asyncio.create_task`; not every task is routed through `TaskSupervisor`. That is a known ownership trade-off documented by the code: `TaskSupervisor` provides centralized handling for registered long-running/background tasks, while short-lived playback callbacks remain close to the music lifecycle.

### Direct attachment audio

The direct-audio path is intentionally restricted. `MusicService.play_direct_audio` accepts only HTTPS URLs hosted by `cdn.discord.app` or `media.discord.net`, requires a non-empty title, and treats the attachment URL as the stream source. This allows an AI attachment request to become a track without turning the bot into an unrestricted URL proxy.

## AI and agent architecture

The AI path is composed from application-level request state, a small workflow graph, policy and coordination services, dynamic tools, and provider adapters.

```text
Discord message
    |
    v
AgentRequestContext + AttachmentRef list
    |
    v
AgentService
    |-- guild settings and policy checks
    |-- per-user rate limit
    |-- channel/global turn coordination
    |-- conversation history preparation
    |-- attachment preparation and cleanup
    |-- dynamic tool selection
    v
OuterAgentWorkflow (LangGraph StateGraph)
    |-- normalize_input
    |-- load_context
    |-- policy_check
    |-- route
    |      |-- direct_audio -> MusicService
    |      `-- ai_agent -> LangChainAgentFactory -> Gemini
    `-- finalize
```

### Serializable request state

`AgentRequestContext` is a frozen, slots-based dataclass. It contains the authorization and routing context needed by tools without carrying Discord framework objects. `PeaceMusicState` is a Pydantic state model with checkpoint-safe fields such as request identity, normalized input, route, attachment references, tool events, and final response. It rejects unknown fields and can serialize itself as JSON.

These choices make state inspectable and suitable for durable graph checkpoints. They also reduce the risk of accidentally persisting a live Discord object, an open file handle, or a provider-specific response object.

### Workflow graph and orchestration

`OuterAgentWorkflow` compiles a LangGraph `StateGraph` with explicit lifecycle nodes and conditional routing. The current graph contains identity nodes for lifecycle stages that are currently handled by `AgentService`; the meaningful graph-local transformation is input normalization and route selection. Policy enforcement and provider invocation remain in `AgentService` so rate limiting, settings, attachment cleanup, conversation history, and turn coordination can be applied consistently around the graph.

This is a deliberate boundary rather than evidence that the graph owns every operation. LangGraph supplies a stable state machine and persistence hook, while the application service remains the policy/orchestration owner.

### Provider isolation

`LangChainAgentFactory` lazily imports the LangChain and Google GenAI integrations and creates a Gemini-backed agent only when an AI turn is requested. The factory receives model name, API key, temperature, and system prompt from typed settings. LangGraph checkpointer and store objects are attached when persistence is configured.

The rest of the agent layer works with application contracts. A provider exception is converted by `AgentService` into `ExternalServiceError`, logged with request/guild/channel context, and reflected in metrics. The model provider can therefore be changed primarily in the infrastructure factory and configuration rather than throughout the cogs and modules.

### Dynamic tools and bounded execution

`ToolRegistry` describes tools by category (`MUSIC`, `MEMORY`, and `DISCORD`) and exposes only categories enabled by the guild’s AI settings. The LangChain bridge wraps registered handlers as structured tools, binds the request context in a closure, validates business arguments, and enforces a per-turn maximum tool-call count.

Tools are thin adapters over application services. For example, music tools call `MusicService` and memory tools call `MemoryService`; they do not contain SQL, yt-dlp extraction, or Discord response logic. Each tool returns a validated `ToolResult` with an application code, message, optional data, and a `user_notified` flag. There is intentionally no unrestricted “think” tool.

Agent execution is bounded at several levels:

- per-user sliding-window rate limiting;
- global and per-channel turn coordination;
- per-turn tool-call limit;
- model recursion limit derived from model-call and tool-call limits;
- an overall AI turn timeout;
- attachment count/type/size limits;
- bounded conversation history and optional character-based compaction.

The thread identifier passed to LangChain is stable per guild/channel (`guild:{guild_id}:channel:{channel_id}`) and per DM channel (`dm:{channel_id}`). This gives the provider/checkpointer a stable conversation key without exposing Discord objects to the model layer.

## Settings, authorization, and policy

Settings are modeled as a validated `GuildSettings` aggregate containing general, music, voice, AI, and memory settings. Pydantic validators enforce bounds such as volume, queue size, playlist size, temperature, timeouts, and valid loop modes.

`GuildSettingsService` is the policy boundary for reads and updates:

- reads use repository-backed defaults and a per-guild TTL cache;
- returned settings are deep-copied so callers cannot mutate cached state accidentally;
- updates use per-guild async locks;
- update authorization is delegated to `SettingsAuthorizer`;
- global ceilings and AI model allowlists are checked before persistence;
- successful changes are audited and invalidate the cache.

Music permissions are modeled as `MusicCapability` values. `DiscordMusicPermissionService` translates Discord member roles, Manage Server status, and voice-channel membership into those capabilities. Manage Server users bypass the configured DJ-role checks; playback and queue-add operations require the user to be in voice and, when applicable, in the same channel as the bot.

This keeps Discord authorization details at the adapter edge while allowing `MusicService` to ask for a capability decision rather than inspect Discord objects directly.

## Memory, attachments, and multimodal requests

### Memory

`MemoryService` gates operations using guild memory settings and creates `MemoryRecord` values with UUIDs, timestamps, namespaces, kinds, and retention expiry. User and channel namespaces are derived from guild/channel/user identifiers. Recall, forget, count, and administrative clear operations are exposed through a repository interface.

The current container wires `LangGraphMemoryRepository`. It maps records to LangGraph Store documents, uses the `content` field for semantic indexing, searches with namespace/filter/kind/limit, checks expiry, and maps results back to application records. The repository layer also contains `PostgresMemoryRepository`, which targets the app-owned `memory_records` table; the composition root currently chooses the LangGraph Store adapter. This gives the project a concrete alternative persistence adapter but means the migration table and active memory storage path are not the same abstraction.

`GeminiEmbeddingFunction` supplies 768-dimensional embeddings through the Google GenAI SDK, offloading the blocking provider call to a worker thread. It is used by the LangGraph Store index configuration when long-term semantic search is enabled.

### Attachments

`AttachmentService` validates external attachments before download:

- maximum attachment count;
- allowed image, video, and audio MIME types;
- maximum bytes per attachment;
- download timeout.

Files are downloaded into a `TemporaryDirectory` with random UUID-based names. `AttachmentProviderWorkflow` then uploads prepared files through `GeminiFileService`, yields provider references for the model request, and deletes uploaded provider references in reverse order in a `finally` block. The result is bounded local disk usage and cleanup even when an AI turn fails.

`HttpAttachmentDownloader` uses `httpx.AsyncClient`, follows no redirects, and maps HTTP failures into application errors. This is both a resource-control and SSRF-reduction measure: the current implementation does not blindly follow redirect chains supplied by remote content.

## Persistence architecture

`PostgresDatabase` owns the asyncpg connection pool. Repositories acquire connections through that database abstraction, while domain and Pydantic models remain outside the SQL implementation.

The current Alembic schema contains:

| Migration | Persistent capability |
| --- | --- |
| `0001_initial_schema` | Guild settings, roles/permissions, disabled users, channel mutes, playlists, playlist tracks, history, and audit events. |
| `0002_playlist_identity` | Idempotent identity additions for playlist/history records. |
| `0003_complete_guild_settings` | Full settings fields used by the current settings aggregate. |
| `0004_memory_records` | App-owned memory records with JSONB namespace/metadata and expiry. |
| `0005_conversation_messages` | Bounded short-term conversation messages with thread indexing. |
| `0006_player_messages` | Persisted guild-to-channel/message identity for the player UI. |

Concrete repositories include settings, access, audit, conversation, DJ roles, history, memory, player messages, and playlists. SQL is kept in repositories, so services do not combine business decisions with query construction.

Short-term conversation history is deliberately bounded. `PostgresConversationRepository` retrieves recent messages in chronological order for prompting and, after appending, deletes older messages beyond its configured maximum. `AgentService` can additionally compact recent messages into a bounded summary when summarization is enabled.

There are two different persistence concerns in the AI subsystem:

1. The conversation repository stores application-level user/assistant messages for prompt preparation.
2. LangGraph persistence stores graph/checkpoint state and the active memory Store.

Keeping these separate lets the application control prompt history independently from graph execution state, at the cost of duplicated state concepts and more than one retention/configuration path.

## Cross-cutting runtime services

### Configuration

`AppSettings` is loaded from environment variables through `pydantic-settings`. Nested settings group Discord intents/token, database URL and pool sizing, AI provider/model behavior, media limits, voice behavior, logging, and operational endpoints. The container passes typed settings downward instead of making individual services read environment variables directly.

### Logging

`core.logging` configures a root handler with `JsonFormatter`. Production mode emits structured JSON containing timestamp, level, logger, and message, with optional request, guild, channel, and user context. This supports container log collection and correlation of a Discord event with its downstream database/provider work.

### Metrics

`MetricsRegistry` is a small in-process Prometheus text-format registry. It supports counters, gauges, summaries, validates metric and label names, and avoids high-cardinality labels in the actual instrumentation. Metrics cover areas such as yt-dlp requests/errors/duration, playback restarts, audio-buffer underruns, and agent turns/tool activity.

The registry intentionally has no external metrics SDK or push path. `/metrics` renders the current process’s values, and a Prometheus-compatible scraper can collect them. The trade-off is low dependency and simple operation versus no built-in aggregation across multiple bot replicas.

### Background tasks

`TaskSupervisor` owns explicitly registered tasks, logs failures through a callback, and cancels/gathers tasks during shutdown. It provides a common lifecycle for background work, while short-lived playback completion and idle-disconnect tasks are still created close to `MusicService` using `asyncio.create_task`. This split keeps playback callbacks simple but requires discipline when adding new long-lived tasks.

## Deployment and production operation

The Dockerfile uses multiple stages:

1. A Deno image supplies the Deno binary for the yt-dlp JavaScript-runtime path.
2. A uv image supplies the dependency manager.
3. `python:3.12-slim` is the runtime image.

The final image installs FFmpeg, copies the required binaries, installs the locked production environment with `uv sync --frozen --no-dev`, sets `PYTHONPATH=/app/src`, creates a non-root `peacemusic` user, and starts with:

```text
alembic upgrade head && python -m peacemusic.main
```

`docker-compose.yml` defines the production-shaped topology:

- `peacemusic` for the bot;
- PostgreSQL 16 with a health check and named data volume;
- `bgutil-provider` for the yt-dlp PO-token provider;
- named volumes for music files, application data, and yt-dlp cache.

The bot container drops all Linux capabilities, enables `no-new-privileges`, sets memory/CPU/PID limits, rotates JSON-file logs, restarts unless stopped, and has a liveness health check. The Compose file constructs `DATABASE_URL` for the internal PostgreSQL service and waits for PostgreSQL health before starting the bot.

CI in `.github/workflows/ci.yml` runs on pushes to `main-v2` and pull requests. It checks dependency locking, Flake8, Black, Compose configuration, unit tests with an 80% coverage threshold, and PostgreSQL integration tests after applying migrations. A successful `main-v2` pipeline builds and publishes a multi-architecture (`amd64`/`arm64`) image to GHCR with latest/SHA tags and build cache.

## Testing approach

The test layout mirrors the architecture:

- domain and module tests exercise queues, settings, permissions, agent contracts, memory policy, and service behavior;
- adapter tests exercise Discord-facing translation and provider adapters with fakes or stubs;
- infrastructure tests cover media, attachments, persistence, metrics, health, and logging boundaries;
- `tests/integration` exercises real PostgreSQL behavior when `DATABASE_URL` is available.

The PostgreSQL integration tests verify behavior that mocks cannot prove, including settings surviving a service restart and LangGraph Store data surviving a persistence restart. The integration job explicitly applies Alembic migrations before running.

The test strategy follows the dependency direction: business services can be tested without live Discord/Gemini/yt-dlp, while a smaller integration surface validates the concrete database and LangGraph persistence wiring. The repository does not claim to provide a live Discord end-to-end test or a live Gemini-provider test; those external systems are represented by boundary tests and fakes in the checked-in test suite.

## Architectural patterns and engineering approaches

### Ports and adapters

Interfaces in module ports describe capabilities such as media resolution, voice playback, repositories, authorization, attachment download/upload, and memory storage. Infrastructure and Discord packages implement or consume those interfaces. This is a pragmatic hexagonal architecture: the code does not attempt to eliminate all framework knowledge, but it keeps the highest-value business rules portable.

### Capability-oriented modules

The modules are grouped by business capability rather than by technical type alone. A developer working on playlists, memory, or access control can usually find its models, ports, service, and repository contract together. Cross-module collaboration happens through service interfaces—for example, autoplay uses settings and media/music abstractions rather than reaching into Discord cogs.

### Application-service orchestration

Services such as `MusicService`, `AgentService`, `GuildSettingsService`, and `MemoryService` coordinate multiple dependencies and enforce invariants. Cogs and tools are delivery adapters. This makes the same behavior available from a slash command, persistent view, or AI tool without duplicating the policy.

### Explicit state and contracts

Frozen dataclasses model request context and media records. Pydantic models validate settings, agent state, attachment references, tool results, and configuration. Explicit states and error types make provider failures distinguishable from validation or permission failures.

### Defensive resource management

The implementation uses connection-pool context managers, temporary-directory cleanup, provider-file cleanup, bounded queues, semaphores, timeouts, retry limits, and orderly cancellation. These controls address the failure modes most likely in a long-lived bot: slow external providers, oversized attachments, stream failure, abandoned voice sessions, and process shutdown during active I/O.

### Async-first with isolated blocking work

The application stays async at its public boundaries. yt-dlp extraction, Gemini file operations, and embedding calls are moved to threads. The code therefore avoids blocking the Discord event loop while retaining libraries whose APIs are synchronous internally.

## Key trade-offs and current limitations

The architecture favors explicit boundaries and operational safety, but those choices have costs:

| Decision | Benefit | Cost or limitation |
| --- | --- | --- |
| In-memory active player state | Low-latency queue/player operations and natural fit for a live voice connection | Playback state is lost on process restart; only history, playlists, settings, and player-message identity are durable. |
| PostgreSQL repositories with direct SQL | Clear queries, strong transactions, and efficient async access | Repository code is coupled to PostgreSQL and requires migrations; there is no database-agnostic ORM layer. |
| Separate conversation repository and LangGraph persistence | Independent control of prompt history and graph/checkpoint state | Two persistence systems represent related AI state and require coordinated retention/configuration decisions. |
| LangGraph plus orchestration in `AgentService` | Visible workflow state and centralized policy/resource control | Some graph nodes are identity placeholders, so the graph is not the sole owner of the full turn lifecycle. |
| Provider adapters behind factories/ports | Tests and provider replacement are easier | Interfaces and translation code add indirection to a relatively small application. |
| In-process Prometheus registry | Very small operational footprint and no SDK dependency | Metrics are process-local and need an external scraper/aggregation strategy for multiple replicas. |
| Bounded retries and timeouts | Provider failures cannot hold a turn or playback forever | A transient failure may still surface to the user once limits are exhausted; retries do not guarantee recovery. |
| Direct FFmpeg source in the current playback path | Simple, familiar Discord voice integration | `BufferedAudioSource` is not currently in the active source pipeline, so its underrun protection is not automatically applied. |
| `TaskSupervisor` alongside local `create_task` calls | Long-lived tasks have a common owner while playback callbacks stay local | Task ownership is split; new background work must be deliberately classified and registered or locally cleaned up. |
| AI tools are enabled by guild settings | Administrators control risk and feature exposure | The model has fewer capabilities when a category is disabled, and each new tool needs registry, adapter, permission, and test work. |
| No live Discord/Gemini CI test | CI is deterministic and does not require secrets or a Discord account | Provider-specific regressions still need manual or separately provisioned environment testing. |

These are properties of the current implementation, not recommendations for an unimplemented redesign.

## Maintainability and extensibility

The current structure supports incremental change in several concrete ways.

To add a new media provider, implement `MediaResolver` in infrastructure, map its errors to application errors, and wire it in the container. `MusicService`, queue logic, permissions, history, and cogs do not need provider-specific code.

To add a new AI capability, implement a handler over an existing application service or add a new module service, describe it in `ToolRegistry`, expose only the appropriate settings category, and test the `ToolResult` contract. The model-facing adapter does not need SQL or Discord details.

To add a persistent business feature, define a domain model/service contract, add a PostgreSQL repository, create an Alembic revision, wire the repository in `build_container`, and add unit plus integration coverage where transactional behavior matters.

To change Discord presentation, modify a cog, presenter, or view while leaving the underlying service contract intact. The same service can continue to be called by commands, UI callbacks, and agent tools.

To operate the service in production, configuration is supplied through the environment, schema setup is explicit, health/readiness are probeable, logs are structured, metrics are scrapeable, and the container has resource and privilege limits.

## Developer orientation

The most useful entry points for a new engineer are:

1. `src/peacemusic/bootstrap/container.py` — see the real dependency graph.
2. `src/peacemusic/main.py` — see process startup, signal handling, and shutdown.
3. `src/peacemusic/adapters/discord/bot.py` — see Discord wiring and cog registration.
4. The relevant `src/peacemusic/modules/*/service.py` — see application behavior.
5. `src/peacemusic/infrastructure/*` — see concrete provider and persistence adapters.
6. `migrations/versions` — see the durable schema contract.
7. `tests` and `.github/workflows/ci.yml` — see supported behavior and verification gates.

A useful change path is therefore:

```text
Interaction or operational requirement
          |
          v
Identify the owning capability module
          |
          v
Change the service/domain contract
          |
          +--> update or add a port
          +--> implement infrastructure/Discord adapter
          +--> wire it in bootstrap.container
          +--> add focused tests
          `--> add a migration when durable schema changes
```

## Interview-level architectural summary

PeaceMusic is a modular asynchronous Python service whose composition root assembles Discord delivery adapters, application services, provider adapters, and PostgreSQL repositories. Its most important engineering choice is dependency direction: music, settings, agent, and memory behavior are expressed through application services and validated contracts, while Discord, Gemini, yt-dlp, FFmpeg, HTTP, and SQL details remain replaceable edges.

That structure is valuable in an interview because it demonstrates more than framework usage. It shows explicit dependency injection, bounded external work, domain-level permission and playback rules, durable schema evolution, provider isolation, operational health/metrics, and tests that separate fast unit coverage from real PostgreSQL integration. The trade-offs are also explicit: active playback remains process-local, AI has two persistence concerns, metrics are in-process, and a few runtime tasks remain locally managed. The architecture is therefore pragmatic rather than dogmatic—small enough to operate as one service, but decomposed enough to evolve and test safely.
