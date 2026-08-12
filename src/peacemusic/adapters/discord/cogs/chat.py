"""Thin Discord message adapter for AgentService."""

from __future__ import annotations

import logging
from uuid import uuid4

import discord
from discord.ext import commands

from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.access.service import AccessControlService
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.service import AgentService
from peacemusic.modules.agent.state import AttachmentRef

logger = logging.getLogger(__name__)


class ChatCog(commands.Cog):
    def __init__(
        self, service: AgentService, access: AccessControlService | None = None
    ) -> None:
        self._service = service
        self._access = access

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            return
        if self._access is not None and await self._access.is_suppressed(
            guild_id=message.guild.id,
            user_id=message.author.id,
            channel_id=message.channel.id,
        ):
            return

        settings = await self._service.get_settings(message.guild.id)
        if not settings.ai.enabled:
            return
        if (
            settings.ai.channel_id is not None
            and message.channel.id != settings.ai.channel_id
        ):
            return
        if settings.ai.require_mention and self._service_bot_id not in {
            user.id for user in message.mentions
        }:
            return

        text = message.content
        if self._service_bot_id:
            text = text.replace(f"<@{self._service_bot_id}>", "").strip()
            text = text.replace(f"<@!{self._service_bot_id}>", "").strip()
        context = AgentRequestContext(
            request_id=str(uuid4()),
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            user_name=message.author.display_name,
            user_voice_channel_id=(
                getattr(getattr(message.author, "voice", None), "channel", None).id
                if getattr(getattr(message.author, "voice", None), "channel", None)
                else None
            ),
            bot_voice_channel_id=None,
            can_manage_guild=bool(
                getattr(
                    getattr(message.author, "guild_permissions", None),
                    "manage_guild",
                    False,
                )
            ),
        )
        attachments = [
            AttachmentRef(
                attachment_id=str(attachment.id),
                filename=attachment.filename,
                content_type=attachment.content_type,
                size_bytes=attachment.size,
                url=attachment.url,
            )
            for attachment in message.attachments
        ]
        try:
            async with message.channel.typing():
                state = await self._service.handle(
                    context,
                    text,
                    attachments=attachments,
                )
            for chunk in split_message(state.final_response or ""):
                await message.channel.send(chunk)
            if settings.ai.reactions_enabled:
                await message.add_reaction("🤖")
        except PeaceMusicError as exc:
            logger.warning("Agent request failed: %s", exc)
        except Exception:  # noqa: BLE001 - Discord listener must not die
            logger.exception("Unexpected agent listener failure")

    @property
    def _service_bot_id(self) -> int | None:
        bot = getattr(self, "bot", None)
        return getattr(getattr(bot, "user", None), "id", None)


def split_message(text: str, *, limit: int = 2000) -> list[str]:
    """Split model output into Discord-safe chunks without empty sends."""

    if limit < 1:
        raise ValueError("limit must be positive")
    if not text:
        return []
    return [text[index : index + limit] for index in range(0, len(text), limit)]
