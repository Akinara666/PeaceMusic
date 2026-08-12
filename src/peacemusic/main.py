"""Production lifecycle entrypoint for the v2 application."""

from __future__ import annotations

import asyncio
import logging
import signal

from peacemusic.adapters.discord.bot import PeaceMusicV2Bot
from peacemusic.bootstrap.container import build_container
from peacemusic.core.config import AppSettings
from peacemusic.core.logging import configure_logging

logger = logging.getLogger(__name__)


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    stop_event: asyncio.Event,
) -> None:
    """Convert process termination signals into an orderly lifecycle stop."""

    for signal_name in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, signal_name, None)
        if signum is None:
            continue
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:
            logger.debug("Signal handlers are unavailable on this platform")


async def run(settings: AppSettings | None = None) -> None:
    resolved_settings = settings or AppSettings()
    configure_logging(
        resolved_settings.observability.log_level,
        json_logs=resolved_settings.observability.environment == "production",
    )
    container = build_container(resolved_settings)
    bot = PeaceMusicV2Bot(container)
    stop_event = asyncio.Event()
    install_signal_handlers(asyncio.get_running_loop(), stop_event)

    await container.start()
    try:
        async with bot:
            bot_task = asyncio.create_task(
                bot.start(resolved_settings.discord.token.get_secret_value()),
                name="discord-bot",
            )
            stop_waiter = asyncio.create_task(stop_event.wait(), name="shutdown-waiter")
            done, _pending = await asyncio.wait(
                (bot_task, stop_waiter),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if bot_task in done:
                bot_task.result()
            else:
                logger.info("Shutdown signal received")
                bot_task.cancel()
                await asyncio.gather(bot_task, return_exceptions=True)
            stop_waiter.cancel()
            await asyncio.gather(stop_waiter, return_exceptions=True)
    finally:
        container.mark_discord_ready(False)
        await container.stop()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
