# PeaceMusic

PeaceMusic is a Discord bot powered by Google Gemini for multi-turn chat and music control in voice channels. It can stream tracks from YouTube and other sources via yt-dlp, downloading them for local caching when needed.

Russian documentation is available in [README.ru.md](README.ru.md).

## Features
- Gemini-based AI chat suitable for free-form conversation and music commands.
- Music commands: `play` (search or direct URL), `skip`, `stop`, `seek`, `set_volume`, `summon`, `disconnect`.
- Conversation history with persistent context stored on disk.

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


## Environment Variables
Configure them in `.env` (see `.env.example`).

- `DISCORD_BOT_TOKEN` - your Discord bot token.
- `CHATBOT_CHANNEL_ID` - channel ID for AI chat (optional; omit to respond in any channel).
- `GEMINI_API_KEY` - Google Gemini Developer API key.
- `MUSIC_DIRECTORY` - path for downloaded/cached tracks (defaults to `music_files`).

## Sample Prompts (in chat)
Use natural language to trigger Tool Calling and music features: `play <song name>`, `seek to 1:23`, `set volume to 50%`, `skip this track`, `disconnect from voice`, `join my channel`, etc.

## Updating
```bash
git pull
pip install -r requirements.txt
```
