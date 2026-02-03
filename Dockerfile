FROM python:3.12-slim

# Install system dependencies
# ffmpeg: required for audio playback
# git: required if installing deps from git (not currently used)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl unzip nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install Deno (specifically requested)
RUN curl -fsSL https://deno.land/install.sh | sh && \
    mv /root/.deno/bin/deno /usr/local/bin/deno

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Run the bot
CMD ["python", "main.py"]
