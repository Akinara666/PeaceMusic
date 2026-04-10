# PeaceMusic

PeaceMusic is a Discord bot powered by Google Gemini for multi-turn chat and music control in voice channels. It can stream tracks from YouTube and other sources via yt-dlp, downloading them for local caching when needed.

Russian documentation is available in [README.ru.md](README.ru.md).

## Features
- Gemini-based AI chat suitable for free-form conversation and music commands.
- Music commands: `play` (search or direct URL), `skip`, `stop`, `seek`, `set_volume`, `summon`, `disconnect`.
- SQLite-backed chat memory with recent context, semantic recall, and rolling global summaries.

## Requirements
- Python 3.10 or newer.
- FFmpeg available in `PATH` (required by `discord.FFmpegPCMAudio`).
- **Deno** or **Node.js** (required by `yt-dlp` for YouTube signature handling).
- Secrets for external services: Discord Bot Token and Gemini API Key.

## Project Structure
- `main.py` - application entry point and bot bootstrap.
- `cogs/ai_cog.py` - Gemini chat cog and command dispatcher.
- `cogs/music_cog.py` - music playback cog, queue, and voice helpers.
- `utils/` - shared utilities: Gemini helpers (`gemini_voice.py`), tool schema (`tools.py`), default prompt, etc.
- `config.py` - configuration loader; reads environment variables from `.env`.

## Quick Start (development)
```bash
# 1) Clone the repository and enter the project folder
git clone https://github.com/Akinara666/PeaceMusic.git && cd PeaceMusic

# 2) Create a virtual environment
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows (PowerShell)
# .\.venv\Scripts\Activate.ps1

# 3) Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4) Configure secrets
cp .env.example .env  # Windows: copy .env.example .env
# Fill out .env with your tokens and other settings (see next section)

# 5) Launch the bot
python main.py
```

## Running with Docker (Recommended for Server)

1.  **Install Docker & Docker Compose** on your server.
2.  **Configure .env** (as described above).
3.  **Run**:
    ```bash
    docker-compose up -d --build
    ```
    The bot will start in the background and restart automatically on reboot.

### Useful Commands
- **Restart**: `docker-compose restart` (e.g. after changing .env)
- **Logs**: `docker-compose logs -f --tail=100`
- **Stop**: `docker-compose down`


## Environment Variables
Configure them in `.env` (see `.env.example`).

- `DISCORD_BOT_TOKEN` - your Discord bot token.
- `CHATBOT_CHANNEL_ID` - channel ID for AI chat (optional; omit to respond in any channel).
- `GEMINI_API_KEY` - Google Gemini Developer API key.
- `GEMINI_SOCKS_PROXY` - optional SOCKS5 proxy for Gemini API traffic, for example `socks5://127.0.0.1:40000`.
- `CHAT_MEMORY_DB` - path to the SQLite memory database (defaults to `chat_memory.sqlite3`; Docker overrides it to `/app/data/chat_memory.sqlite3`).
- `GEMINI_RESPONSE_MODEL` - response generation model (defaults to `gemini-3.1-flash-lite`).
- `GEMINI_SUMMARY_MODEL` - background summary model (defaults to `gemini-3.1-flash-lite`).
- `GEMINI_EMBEDDING_MODEL` - embedding model for semantic memory (defaults to `gemini-embedding-2-preview`).
- `MUSIC_DIRECTORY` - path for downloaded/cached tracks (defaults to `music_files`).
- `YTDL_USE_COOKIES` - enable `yt-dlp` cookies support (`false` by default).
- `YTDL_COOKIE_FILE` - path to a Netscape-format cookies file when cookies are enabled (defaults to `data/cookies.txt`).

`GEMINI_SOCKS_PROXY` applies to response generation, embeddings, file checks, and background summaries because all Gemini SDK calls share the same client.

### Cookies
- Cookies are disabled by default.
- To enable them, set `YTDL_USE_COOKIES=true` and place a Netscape-format cookies file at `data/cookies.txt`, or set a custom path via `YTDL_COOKIE_FILE`.
- Docker no longer bind-mounts `cogs/cookies.txt`, so removing that file will not break container startup.

## Sample Prompts (in chat)
Use natural language to trigger Tool Calling and music features: `play <song name>`, `seek to 1:23`, `set volume to 50%`, `skip this track`, `disconnect from voice`, `join my channel`, etc.

## Slash Commands
- `/bot_access action:<Disable|Enable|Status> member:<user>` - manage whether a specific server member can interact with the bot in text chat. Requires `Manage Server` or administrator permissions.

## Updating
```bash
git pull
pip install -r requirements.txt
```
