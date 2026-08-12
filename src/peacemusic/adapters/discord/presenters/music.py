"""Discord presentation of music service results."""

from __future__ import annotations

import discord

from peacemusic.modules.music.models import Track
from peacemusic.modules.music.player import GuildPlayer


def track_embed(
    track: Track, *, description: str = "Added to the queue"
) -> discord.Embed:
    return discord.Embed(
        title=track.title,
        url=track.webpage_url,
        description=description,
        color=discord.Color.green(),
    )


def player_embed(player: GuildPlayer) -> discord.Embed:
    current = player.current_track.title if player.current_track else "Nothing playing"
    queue = player.queue.list()
    description = (
        f"**Now playing:** {current}\n"
        f"**Status:** `{player.status.value}`\n"
        f"**Volume:** {player.volume}%\n"
        f"**Queued:** {len(queue)}"
    )
    return discord.Embed(
        title="🎵 PeaceMusic Player",
        description=description,
        color=discord.Color.blurple(),
    )
