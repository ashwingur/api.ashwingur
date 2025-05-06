# clash_commands.py

import sys
import discord
from discord import app_commands
import aiohttp
import urllib.parse
from discord.ext import commands, tasks
import os
from typing import Tuple, Optional
from datetime import datetime, timezone

BASE_URL = "http://flask_app:5000"
DEFAULT_CLAN_TAG = "#220QP2GGU"

GUILD_ID = 1081503290132545596
CHANNEL_BOT = 1089437682679165028
CHANNEL_WAR = 1081513755415949393

async def get_current_clan_war(data: dict) -> Tuple[Optional[dict], int]:
    """
    Returns the current active or preparation clan war object and the appropriate max_attacks.
    data is the object received from the /clashofclans/fullclan endpoint.
    """
    # Check standard war
    if "war" in data and data["war"] and data["war"].get("state") in ["inWar", "preparation"]:
        return data["war"], 2

    # Check CWL wars
    if data.get("cwl_wars"):
        for war in data["cwl_wars"]:
            if data["tag"] in [war["clan"]["tag"], war["opponent"]["tag"]]:
                if war["state"] == "inWar":
                    return war, 1
        for war in data["cwl_wars"]:
            if data["tag"] in [war["clan"]["tag"], war["opponent"]["tag"]] and war["state"] == "preparation":
                return war, 1

    return None, 0

async def create_clan_war_embed(data, clan_war, max_attacks: int):
    embed = discord.Embed(
    title=f"War Info: {data.get('name', 'Unknown')}",
    description=f"Tag: {data.get('tag')}",
    color=discord.Color.green()
    )

    embed.set_thumbnail(url=data.get("badgeUrls").get("small"))

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

        elapsed = seconds_since_coc_timestamp(clan_war["endTime"])
        time_remaining = format_seconds_to_time_string(abs(elapsed))

        embed.add_field(name="War Status", value=state, inline=False)
        embed.add_field(name="Time Until War Ends", value=time_remaining, inline=False)

        embed.add_field(name=clan1["name"], value=f"💥: {clan1['destructionPercentage']:.1f}%\n⭐: {clan1['stars']}\n⚔️: {clan1['attacks']}", inline=True)
        embed.add_field(name=clan2["name"], value=f"💥: {clan2['destructionPercentage']:.1f}%\n⭐: {clan2['stars']}\n⚔️: {clan2['attacks']}", inline=True)

        if state == "In war":
            attacks_todo = [
                member["name"]
                for member in clan1["members"]
                if len(member.get("attacks") or []) < max_attacks
            ]
            if attacks_todo:
                embed.add_field(name="Attacks Pending", value=", ".join(attacks_todo), inline=False)
            else:
                embed.add_field(name="Attacks Pending", value="All players have attacked!", inline=False)
    else:
        embed.add_field(name="Status", value="Clan war log is private, or the clan is not in a war")
    
    return embed

def seconds_since_coc_timestamp(timestamp_str: str) -> float:
    """
    Given a Clash of Clans-style timestamp (e.g., '20250505T092622.000Z'),
    returns the number of seconds that have passed since that time.
    """
    try:
        war_time = datetime.strptime(timestamp_str, "%Y%m%dT%H%M%S.%fZ")
        war_time = war_time.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        return (now_utc - war_time).total_seconds()
    except ValueError as e:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}") from e

def format_seconds_to_time_string(seconds: int) -> str:
    """
    Converts seconds into a string of format 'Xd Yh Zm',
    omitting 'Xd' or 'Yh' if not relevant, and converting
    exact days to hours (e.g., 1d 0h → 24h). Ensures no decimals.
    """
    total_minutes = int(seconds // 60)
    total_hours = int(total_minutes // 60)
    minutes = int(total_minutes % 60)
    days = int(total_hours // 24)
    hours = int(total_hours % 24)

    parts = []
    if days > 0 and hours == 0:
        # Show full hours instead of "1d 0h"
        parts.append(f"{days * 24}h")
    else:
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0 or days > 0:
            parts.append(f"{hours}h")

    parts.append(f"{minutes}m")
    return " ".join(parts)

class ClashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_sent_war_end_time = None
        self.last_sent_war_prep_time = None
        self.send_daily_war_status.start()

    @app_commands.command(name="war", description="Check the current war status")
    @app_commands.describe(clan_tag="The tag of the clan (optional)")
    async def war(self, interaction: discord.Interaction, clan_tag: str = DEFAULT_CLAN_TAG):
        await interaction.response.defer()

        encoded_tag = urllib.parse.quote(clan_tag)
        url = f"{BASE_URL}/clashofclans/fullclan/{encoded_tag}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Unable to fetch clan data")
                        return

                    data = await resp.json()
                    clan_war, max_attacks = await get_current_clan_war(data)
                    embed = await create_clan_war_embed(data, clan_war, max_attacks)

                    await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @tasks.loop(seconds=300)  # Run every 5 min
    async def send_daily_war_status(self):
        guild_id = GUILD_ID
        channel_id = CHANNEL_WAR
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        encoded_tag = urllib.parse.quote(DEFAULT_CLAN_TAG)
        url = f"{BASE_URL}/clashofclans/fullclan/{encoded_tag}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await channel.send("Unable to fetch clan data")
                        return

                    data = await resp.json()
                    clan_war, max_attacks = await get_current_clan_war(data)
                    
                    if not clan_war:
                        return

                    end_time = clan_war["endTime"]
                    prep_time = clan_war["preparationStartTime"]


                    elapsed = seconds_since_coc_timestamp(end_time)
                    prep_elapsed = seconds_since_coc_timestamp(prep_time)

                    # Send prep time as soon as war prep starts
                    should_send_prep = (
                        prep_elapsed < 3600 and prep_time != self.last_sent_war_prep_time
                    )
                    # Send end time 3 hours before
                    should_send_end = (
                        elapsed > -10800 and end_time != self.last_sent_war_end_time
                    )

                    if should_send_prep or should_send_end:
                        embed = await create_clan_war_embed(data, clan_war, max_attacks)
                        await channel.send(embed=embed)

                        if should_send_prep:
                            self.last_sent_war_prep_time = prep_time

                        if should_send_end:
                            self.last_sent_war_end_time = end_time

        except Exception as e:
            await channel.send(f"Error: {e}")

    @send_daily_war_status.before_loop
    async def before_send(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(ClashCommands(bot))
