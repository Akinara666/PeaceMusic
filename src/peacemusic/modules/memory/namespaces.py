"""Stable LangGraph Store namespace conventions."""

from __future__ import annotations


def guild_namespace(guild_id: int) -> tuple[str, ...]:
    return ("guild", str(guild_id), "memory")


def user_namespace(guild_id: int, user_id: int) -> tuple[str, ...]:
    return ("guild", str(guild_id), "user", str(user_id), "memory")


def channel_namespace(guild_id: int, channel_id: int) -> tuple[str, ...]:
    return ("guild", str(guild_id), "channel", str(channel_id), "memory")
