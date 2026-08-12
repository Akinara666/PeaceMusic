# PeaceMusic v2

PeaceMusic v2 is a Discord bot built around a layered application architecture:

- `discord.py` adapters for commands, views, and voice;
- `MusicService` and guild-scoped runtime players;
- `yt-dlp` and FFmpeg for first-party playback;
- PostgreSQL for guild settings, playlists, playback history, memory, and audit events;
- LangChain-compatible agent tools with checkpoint-safe outer workflow state.

Lavalink is not used.

## Requirements

- Python 3.12+
- PostgreSQL 16+
- FFmpeg
- Docker and Docker Compose for container deployment
- Discord bot token and Gemini API key

## Local development

```bash
uv sync --group dev
cp .env.example .env
```

Set at least `DISCORD_BOT_TOKEN`, `GOOGLE_API_KEY`, and `DATABASE_URL` in `.env`.

Run migrations and start the bot:

```bash
alembic upgrade head
PYTHONPATH=src python -m peacemusic.main
```

Run quality checks:

```bash
black --check src tests
flake8 src scripts tests
pytest --cov=src/peacemusic --cov-fail-under=80
```

For a reproducible environment, keep `uv.lock` in sync with `pyproject.toml`.

To import supported data from a PeaceMusic v1 SQLite database after applying
the v2 migrations:

```bash
uv run python scripts/migrate_v1_sqlite.py ./old.sqlite3 \
  --database-url "$DATABASE_URL" --dry-run
```

The importer does not copy raw conversation history or legacy embedding blobs;
explicit text memories are re-indexed by the v2 semantic memory store.

## Docker deployment

```bash
docker compose up --build
```

The image runs `alembic upgrade head` before starting the bot. PostgreSQL data,
application data, and music files are kept in Compose volumes or configured host
directories.

## Discord commands

Configuration:

- `/setup` — initial guild setup wizard
- `/settings` — interactive guild settings panel

Music:

- `/play`, `/search`, `/pause`, `/resume`, `/skip`, `/stop`, `/leave`
- `/volume`, `/loop`, `/queue`, `/remove`, `/move`, `/shuffle`, `/clear`
- `/nowplaying`, `/autoplay`, `/history`
- `/playlist create|delete|add|remove|play|list`

Memory administration:

- `/memory status`
- `/memory stats`
- `/memory forget`
- `/memory clear-channel`
- `/memory clear-user`

Destructive settings and memory operations are authorized in application services,
not by the language model.

## Project structure

```text
src/peacemusic/
├── adapters/discord/       Discord commands, views, presenters, voice
├── bootstrap/              Composition root and lifecycle
├── core/                   Configuration, errors, tasks, logging
├── infrastructure/        PostgreSQL, media, FFmpeg, health, LLM adapters
└── modules/                Agent, audit, history, memory, music, playlists, settings

migrations/                 Alembic schema revisions
tests/                      Unit and adapter boundary tests
```

Guild-specific behavior belongs in PostgreSQL and can be changed through Discord
without editing `.env`, rebuilding the image, or restarting the bot.
