FROM denoland/deno:bin-2.9.4 AS deno

FROM python:3.12-slim

# Install system dependencies
# ffmpeg: required for audio playback
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# yt-dlp requires a supported JavaScript runtime for YouTube challenges.
# Deno is its recommended runtime and is enabled by default.
COPY --from=deno /deno /usr/local/bin/deno
RUN deno --version

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

RUN groupadd --system peacemusic && \
    useradd --system --gid peacemusic --home-dir /app peacemusic && \
    mkdir -p /app/data /app/music_files && \
    chown -R peacemusic:peacemusic /app

USER peacemusic

# Run the bot
CMD ["python", "main.py"]
