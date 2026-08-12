"""Serializable request context passed to agent tools and policies."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class AgentRequestContext:
    request_id: str
    guild_id: int | None
    channel_id: int
    user_id: int
    user_name: str
    user_voice_channel_id: int | None = None
    bot_voice_channel_id: int | None = None
    can_manage_guild: bool = False
    member_role_ids: tuple[int, ...] = ()
    dj_role_ids: tuple[int, ...] = ()

    def to_checkpoint(self) -> dict[str, object]:
        """Return only primitive checkpoint-safe values."""

        return asdict(self)
