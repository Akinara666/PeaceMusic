
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from cogs.ai_cog import GeminiChatCog
from cogs.music_cog import Music
from config import DISCORD_BOT_TOKEN, DISCORD_STATUS_MESSAGE, INTENTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class PeaceMusicBot(commands.Bot):
    async def setup_hook(self) -> None:
        music_cog = Music(self)
        chat_cog = GeminiChatCog(self)
        chat_cog.set_music_cog(music_cog)

        await self.add_cog(music_cog)
        await self.add_cog(chat_cog)
        await self.tree.sync()


bot = PeaceMusicBot(command_prefix="!", intents=INTENTS)


@bot.event
async def on_ready() -> None:
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name=DISCORD_STATUS_MESSAGE)
    )
    logging.info("Logged in as %s (%s)", bot.user, bot.user.id)


def main() -> None:
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
