FROM denoland/deno:bin-2.9.2 AS deno
FROM ghcr.io/astral-sh/uv:0.12.3 AS uv

FROM python:3.12-slim

# Install system dependencies
# ffmpeg: required for audio playback
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# yt-dlp requires a supported JavaScript runtime for YouTube challenges.
# Deno is its recommended runtime and is enabled by default.
COPY --from=deno /deno /usr/local/bin/deno
COPY --from=uv /uv /uvx /bin/
RUN deno --version

WORKDIR /app
ENV PYTHONPATH=/app/src

# Install the locked production dependency graph before copying the rest of the
# application so Docker can reuse this layer when only source files change.
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH=/app/.venv/bin:$PATH

# Copy source code
COPY . .

RUN groupadd --system peacemusic && \
    useradd --system --gid peacemusic --home-dir /app peacemusic && \
    mkdir -p /app/data /app/music_files /app/.cache/yt-dlp && \
    chown -R peacemusic:peacemusic /app

USER peacemusic
ENV HOME=/app

# Run the bot
CMD ["sh", "-c", "alembic upgrade head && exec python -m peacemusic.main"]
