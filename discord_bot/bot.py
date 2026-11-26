import logging
import os

import discord
from discord.ext import commands

import coc_http

log = logging.getLogger("bot")

EXTENSIONS = (
    "clash_commands",
    "clash_war_board",
    "transportopendata_commands",
    "torn_commands",
)


class Bot(commands.Bot):
    async def setup_hook(self):
        # setup_hook runs once per process. on_ready runs again on every reconnect, so loading
        # extensions there raised ExtensionAlreadyLoaded and re-synced commands each time.
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
            except Exception:
                # One broken cog shouldn't take the rest of the bot down
                log.exception("Failed to load extension %s", extension)
        try:
            synced = await self.tree.sync()
            log.info("Synced %d global slash command(s)", len(synced))
        except discord.HTTPException:
            log.exception("Failed to sync commands")

    async def close(self):
        await coc_http.close_session()
        await super().close()


intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
bot = Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    log.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.content.lower() == 'ping':
        await message.channel.send('pong')


if __name__ == "__main__":
    # root_logger=True sends our own loggers (clash.*, bot) to stdout alongside discord.py's
    bot.run(os.getenv("DISCORD_BOT_TOKEN"), root_logger=True)
