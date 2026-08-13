"""Discord presentation of music service results."""

from __future__ import annotations

import discord

from peacemusic.modules.music.models import Track
from peacemusic.modules.music.player import GuildPlayer


def _format_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "Unknown"
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes}:{remainder:02d}"


def track_embed(
    track: Track,
    *,
    description: str = "✅ Added to the queue",
    queue_position: int | None = None,
    now_playing: bool = False,
) -> discord.Embed:
    embed = discord.Embed(
        title=track.title,
        url=track.webpage_url or track.source_url,
        description=description,
        color=discord.Color.green(),
    )
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    if track.uploader:
        embed.add_field(name="Artist / channel", value=track.uploader, inline=True)
    embed.add_field(
        name="Duration", value=_format_duration(track.duration), inline=True
    )
    embed.add_field(name="Requested by", value=f"<@{track.requested_by}>", inline=True)
    if now_playing:
        position = "▶️ Now playing"
    elif queue_position is not None:
        position = f"#{queue_position} in queue"
    else:
        position = "Waiting"
    embed.add_field(name="Queue", value=position, inline=True)
    embed.set_footer(text="PeaceMusic • Music queue")
    return embed


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
