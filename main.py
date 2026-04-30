from __future__ import annotations

import asyncio
import logging
import signal

import discord
from discord.ext import commands

from cogs.ai_cog import GeminiChatCog
from cogs.music_cog import Music
from config import DISCORD_BOT_TOKEN, DISCORD_STATUS_MESSAGE, INTENTS

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


class PeaceMusicBot(commands.Bot):
    async def setup_hook(self) -> None:
        music_cog = Music(self)
        chat_cog = GeminiChatCog(self)

        await self.add_cog(music_cog)
        await self.add_cog(chat_cog)
        await self.tree.sync()


bot = PeaceMusicBot(command_prefix="!", intents=INTENTS)


@bot.event
async def on_ready() -> None:
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening, name=DISCORD_STATUS_MESSAGE
        )
    )
    logging.info("Logged in as %s (%s)", bot.user, bot.user.id)


async def _shutdown(reason: str) -> None:
    logger.info("Graceful shutdown initiated: %s", reason)
    # Disconnect from voice cleanly so the queue/state cleanup hooks fire.
    music_cog = bot.get_cog("Music")
    if music_cog is not None:
        voice_client = getattr(music_cog, "voice_client", None)
        if voice_client is not None:
            try:
                await voice_client.disconnect(force=True)
            except Exception:  # noqa: BLE001 - best effort
                logger.exception("Error disconnecting voice during shutdown")
    # Cancel pending summary tasks; cog_unload will not be awaited otherwise.
    chat_cog = bot.get_cog("GeminiChatCog")
    if chat_cog is not None:
        pending = list(getattr(chat_cog, "_summary_tasks", {}).values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    await bot.close()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for sig_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(
                sig,
                lambda name=sig_name: asyncio.create_task(_shutdown(name)),
            )
        except NotImplementedError:
            # Windows event loop doesn't support add_signal_handler; fall back to
            # the default KeyboardInterrupt path bot.run already provides.
            return


async def _run() -> None:
    _install_signal_handlers(asyncio.get_running_loop())
    async with bot:
        await bot.start(DISCORD_BOT_TOKEN)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, shutting down")


if __name__ == "__main__":
    try:
        import uvloop

        uvloop.install()
    except ImportError:
        pass
    main()
