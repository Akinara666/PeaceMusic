FROM python:3.12-slim

# Install system dependencies
# ffmpeg: required for audio playback
# nodejs: JavaScript runtime used by yt-dlp for signature extraction
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg nodejs && \
    rm -rf /var/lib/apt/lists/*

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
