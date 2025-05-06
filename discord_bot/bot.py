import sys
import discord
import os
from discord import app_commands
from discord.ext import commands
import aiohttp
import urllib.parse
from pprint import pprint

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

BASE_URL = "http://flask_app:5000"
DEFAULT_CLAN_TAG = "#220QP2GGU"
THE_ORGANISATION_GUILD_TAG = 1081503290132545596


@bot.event
async def on_ready():
    print(f'Bot logged in as {bot.user}')
    try:
        synced = await bot.tree.sync(guild=discord.Object())
        print(f"Synced {len(synced)} slash command(s) to guild {THE_ORGANISATION_GUILD_TAG}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.event
async def on_message(message):
    # print(f"received message: {message.content}", file=sys.stderr)
    if message.author.bot:
        return
    if message.content.lower() == 'ping':
        await message.channel.send('pong')

@bot.tree.command(name="war", description="Check the current war status")
@app_commands.describe(clan_tag="The tag of the clan (optional)")
async def war(interaction: discord.Interaction, clan_tag: str = DEFAULT_CLAN_TAG):
    await interaction.response.defer()  # show loading state

    encoded_tag = urllib.parse.quote(clan_tag)
    url = f"{BASE_URL}/clashofclans/fullclan/{encoded_tag}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"Unable to fetch clan data")
                    return

                data = await resp.json()

                clan_war = None
                if "war" in data and data["war"] and data["war"].get("state") in ["inWar", "preparation"]:
                    clan_war = data["war"]
                    max_attacks = 2
                if data.get("cwl_wars"):
                    # Find the current active war otherwise find the preparation war
                    clan_war = next(
                        (w for w in data["cwl_wars"] if data["tag"] in [w["clan"]["tag"], w["opponent"]["tag"]] and w["state"] == "inWar"),
                        None
                    ) or next(
                        (w for w in data["cwl_wars"] if data["tag"] in [w["clan"]["tag"], w["opponent"]["tag"]] and w["state"] == "preparation"),
                        None)
                    max_attacks = 1

                # Format and send an embed with the data
                embed = discord.Embed(
                    title=f"War Info: {data.get('name', 'Unknown')}",
                    description=f"Tag: {clan_tag}",
                    color=discord.Color.green()
                )
                if clan_war:
                    clan1 = clan_war["clan"]
                    clan2 = clan_war["opponent"]
                    if clan2["tag"] == data["tag"]:
                        clan1, clan2 = clan2, clan1

                    state = "N/A"
                    if clan_war.get("state") == "preparation":
                        state = "Preparation"
                    elif clan_war.get("state") == "inWar":
                        state = "In War"

                        # Find which members have attacks remaining
                        attacks_todo = []
                        for member in clan1["members"]:
                            attacks = len(member.get("attacks") or [])
                            if attacks < max_attacks:
                                attacks_todo.append(member["name"])

                    embed.add_field(name="War Status", value=state, inline=False)

                    embed.add_field(name=clan1["name"], value=f"💥: {clan1['destructionPercentage']:.1f}%\n⭐: {clan1['stars']}\n⚔️: {clan1['attacks']}", inline=True)
                    embed.add_field(name=clan2["name"], value=f"💥: {clan2['destructionPercentage']:.1f}%\n⭐: {clan2['stars']}\n⚔️: {clan2['attacks']}", inline=True)

                    if state == "In War":
                        if not attacks_todo:
                            embed.add_field(name="Attacks Pending", value="All players have attacked!", inline=False)
                        else:
                            embed.add_field(name="Attacks Pending", value=", ".join(attacks_todo), inline=False)


                else:
                    embed.add_field(name="Status", value="Clan war log is private, or the clan is not in a war")
                await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error: {e}")


bot.run(os.getenv("DISCORD_BOT_TOKEN"))
