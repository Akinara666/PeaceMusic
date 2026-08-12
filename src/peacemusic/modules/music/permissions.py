"""Capability-based music authorization port."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class MusicCapability(StrEnum):
    PLAY = "play"
    PAUSE = "pause"
    RESUME = "resume"
    SKIP = "skip"
    STOP = "stop"
    SET_VOLUME = "set_volume"
    QUEUE_ADD = "queue_add"
    QUEUE_REMOVE = "queue_remove"
    QUEUE_MOVE = "queue_move"
    QUEUE_CLEAR = "queue_clear"
    QUEUE_SHUFFLE = "queue_shuffle"
    LOOP = "loop"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    SEEK = "seek"
    AUTOPLAY = "autoplay"


@dataclass(frozen=True, slots=True)
class MusicRequestContext:
    guild_id: int
    user_id: int
    user_voice_channel_id: int | None = None
    bot_voice_channel_id: int | None = None
    can_manage_guild: bool = False
    member_role_ids: tuple[int, ...] = ()
    dj_role_ids: tuple[int, ...] = ()

    @property
    def has_dj_role(self) -> bool:
        return bool(set(self.member_role_ids).intersection(self.dj_role_ids))


class PermissionService(Protocol):
    async def allowed(
        self, context: MusicRequestContext, capability: MusicCapability
    ) -> bool:
        """Return whether this request may use a capability."""


class AllowAllPermissionService:
    async def allowed(
        self, context: MusicRequestContext, capability: MusicCapability
    ) -> bool:
        return True
