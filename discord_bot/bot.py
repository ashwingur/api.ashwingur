import sys
import discord
import os
from discord.ext import commands
from pprint import pprint

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.load_extension("clash_commands")
    await bot.load_extension("transportopendata_commands")
    await bot.load_extension("torn_commands")
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} global slash command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.content.lower() == 'ping':
        await message.channel.send('pong')

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
