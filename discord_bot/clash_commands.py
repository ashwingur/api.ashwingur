import sys
import discord
from discord import app_commands
import aiohttp
import urllib.parse
from discord.ext import commands, tasks
import os
from typing import List, Tuple, Optional
from datetime import datetime, timezone
from collections import Counter
from clash_events import get_clash_events

BASE_URL = "http://flask_app:5000"
DEFAULT_CLAN_TAG = "#220QP2GGU"
MAX_EMBED_FIELD_LENGTH = 1024
COC_BEARER_TOKEN = os.getenv("COC_BEARER_TOKEN")
COC_PROXY_URL = "https://cocproxy.royaleapi.dev/v1"
COC_PROXY_HEADERS = {
    "Authorization": f"Bearer {COC_BEARER_TOKEN}",
}

GUILD_ID = 1081503290132545596
CHANNEL_BOT = 1089437682679165028
CHANNEL_WAR = 1081513755415949393
CHANNEL_CLAN_CAPITAL = 1081513938606362704
CHANNEL_GENERAL = 1081503290132545599

# Townhall emoji ids <TH{level}:id>
townhall_map = {
    1: "1370746329260888114",
    2: "1370746331043336262",
    3: "1370746332771516567",
    4: "1370746339863822336",
    5: "1370746343202754761",
    6: "1370746345584984074",
    7: "1370746348105895976",
    8: "1370746350093729812",
    9: "1370746351922712690",
    10: "1370746353734385735",
    11: "1370746355332546630",
    12: "1370746357371109376",
    13: "1370746359019475034",
    14: "1370746361124880435",
    15: "1370746363494666321",
    16: "1370746366355312802",
    17: "1370746369010040892",
    18: "1370746329260888114",
}

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
    description=f"Tag: [{data.get('tag')}](https://www.ashwingur.com/ClashOfClans/clan/{data.get('tag').replace('#','')})\n{clan_war['teamSize']} vs {clan_war['teamSize']}",
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

        clan1_summary = f"⭐: {clan1['stars']}\n⚔️: {clan1['attacks']} / {clan_war['teamSize']*max_attacks}\n💥: {clan1['destructionPercentage']:.1f}%\n\n" if state == "In War" else ""
        clan2_summary = f"⭐: {clan2['stars']}\n⚔️: {clan2['attacks']} / {clan_war['teamSize']*max_attacks}\n💥: {clan2['destructionPercentage']:.1f}%\n\n" if state == "In War" else ""

        # Get a summary of townhall numbers in each clan
        clan1_townhalls = dict(sorted(Counter(member["townhallLevel"] for member in clan1["members"]).items(), reverse=True))
        clan2_townhalls = dict(sorted(Counter(member["townhallLevel"] for member in clan2["members"]).items(), reverse=True))

        clan1_summary += ' , '.join(f"{count} <:TH{level}:{townhall_map[level]}>" for level, count in clan1_townhalls.items())
        clan2_summary += ' , '.join(f"{count} <:TH{level}:{townhall_map[level]}>" for level, count in clan2_townhalls.items())


        embed.add_field(name=clan1["name"], value=clan1_summary, inline=True)
        embed.add_field(name=clan2["name"], value=clan2_summary, inline=True)

        if state == "In War":
            attacks_todo = [
                member["name"]
                for member in clan1["members"]
                if len(member.get("attacks") or []) < max_attacks
            ]
            if attacks_todo:
                embed.add_field(name="Attacks Pending", value=", ".join(attacks_todo), inline=False)
            else:
                embed.add_field(name="Attacks Pending", value="All players have attacked! <a:knightcheer:1369254948717723719>", inline=False)
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
    if days == 1 and hours == 0:
        # Show full hours instead of "1d 0h"
        parts.append(f"{days * 24}h")
    else:
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0 or days > 0:
            parts.append(f"{hours}h")

    parts.append(f"{minutes}m")
    return " ".join(parts)

def format_coc_timestamp_to_day_month(timestamp_str: str) -> str:
    """
    Converts a Clash of Clans-style timestamp (e.g., '20250505T092622.000Z')
    to a formatted date string like '5 May' (no leading zero).
    """
    try:
        dt = datetime.strptime(timestamp_str, "%Y%m%dT%H%M%S.%fZ")
        dt = dt.replace(tzinfo=timezone.utc)
        return f"{dt.day} {dt.strftime('%b')}"  # e.g., '5 May'
    except ValueError as e:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}") from e

def create_capital_raid_embed(data, clan_tag):
    """
    Create a Discord embed for the latest capital raid, including relevant details.
    Returns the embed, startTime, and endTime.
    """
    data = data["items"][0]  # Assuming data is the first item in the response

    total_loot = data.get("capitalTotalLoot", 0)
    offensive_reward = data.get("offensiveReward", 0)
    defensive_reward = data.get("defensiveReward", 0)
    raids_completed = data.get("raidsCompleted", 0)
    total_attacks = data.get("totalAttacks", 0)
    districts_destroyed = data.get("enemyDistrictsDestroyed", 0)
    state: str = data.get("state", "N/A State")
    start_date = format_coc_timestamp_to_day_month(data["startTime"])
    end_date = format_coc_timestamp_to_day_month(data["endTime"])

    member_string = ""
    if "members" in data:
        data["members"].sort(key=lambda x: -x["capitalResourcesLooted"])
        for member in data["members"]:
            attacks_info = f' ({member["attacks"]}/6)' if member["attacks"] < 6 else ""
            member_string += f'{member["name"]: <17} {member["capitalResourcesLooted"]:,}{attacks_info}\n'

    embed = discord.Embed(
        title=f"Latest Capital Raid ({clan_tag})",
        color=discord.Color.green(),
        description=f"[{start_date} – {end_date} ({state.capitalize()})](https://www.ashwingur.com/ClashOfClans/clan/{clan_tag.replace('#','')}/ClanCapitalRaidSeasons)"
    )

    embed.add_field(name="Total Loot <:CapitalGold:1369496549138235402>", value=f"{total_loot:,}", inline=True)
    embed.add_field(name="Offensive Reward <:RaidMedal:1369496553445658735>", value=f"{offensive_reward:,}", inline=True)
    embed.add_field(name="Defensive Reward <:RaidMedal:1369496553445658735>", value=f"{defensive_reward:,}", inline=True)
    embed.add_field(name="Raids Completed <:RaidSwords:1369496555194810448>", value=str(raids_completed), inline=True)
    embed.add_field(name="Total Attacks <:RaidSwordSingle:1369496556859818034>", value=str(total_attacks), inline=True)
    embed.add_field(name="Districts Destroyed <:DistrictHall:1369496551075872799>", value=str(districts_destroyed), inline=True)

    if member_string:
        # Split into chunks of 1024 or less, while preserving line breaks
        chunks = []
        current_chunk = ""

        for line in member_string.splitlines(keepends=True):
            if len(current_chunk) + len(line) > MAX_EMBED_FIELD_LENGTH - 6:  # -6 for opening/closing backticks
                chunks.append(f"```{current_chunk}```")
                current_chunk = line
            else:
                current_chunk += line

        if current_chunk:
            chunks.append(f"```{current_chunk}```")

        # Add each chunk as a separate field
        for i, chunk in enumerate(chunks):
            name = f"Players ({len(data['members'])})" if i == 0 else "\u200b"  # empty name for follow-ups
            embed.add_field(name=name, value=chunk, inline=False)

    return embed, data["startTime"], data["endTime"]

class ClashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_sent_war_end_time = None
        self.last_sent_war_prep_time = None
        self.last_sent_capital_end_time = None
        self.clan_members: Optional[List] = None
        self.send_daily_war_status.start()
        self.send_weekly_raid_log.start()
        self.check_membership_change.start()

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
                        await interaction.followup.send("Unable to fetch clan data.")
                        return

                    data = await resp.json()
                    clan_war, max_attacks = await get_current_clan_war(data)
                    if not clan_war:
                        await interaction.followup.send("Clan is not in war or war log is private.")
                    embed = await create_clan_war_embed(data, clan_war, max_attacks)

                    await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(name="events", description="Check current and upcoming clash of clans events")
    async def war(self, interaction: discord.Interaction):
        await interaction.response.defer()
        events = get_clash_events()

        embed = discord.Embed(
            title=f"Event dates 📅",
            color=discord.Color.dark_magenta(),
            description=f"Ongoing and upcoming clash of clans events"
        )

        for event in events:
            name = event["event"]
            ongoing = event["ongoing"]
            event_datetime = event["datetime"]
            time_remaining = event["time_remaining"]

            msg = ""
            if ongoing:
                msg += f"🟢 Ends in `{format_seconds_to_time_string(time_remaining.total_seconds())}`"
            else:
                msg += f"🟡 Starts in {format_seconds_to_time_string(time_remaining.total_seconds())}"

            embed.add_field(name=name, value=msg, inline=False)

        await interaction.followup.send(embed=embed)



    @tasks.loop(seconds=300)  # Run every 5 min
    async def send_daily_war_status(self):
        return
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

    @app_commands.command(name="activity", description="Check when TheOrganisation members were last active")
    @app_commands.describe(days="Days ago to filter by (default = 5)", name="Player name, overrides days filter (optional)")
    async def activity(self, interaction: discord.Interaction, days: int = 5, name: str = None):
        """
        Send player history, applying any relevant name and day filters.
        """
        await interaction.response.defer()
        url = f"{BASE_URL}/clashofclans/players"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Unable to fetch activity data")
                        return
                    
                    data = await resp.json()
                    # Sort by activity ascending
                    data.sort(key=lambda x: datetime.fromisoformat(x["activity_change_date"]) if x.get("activity_change_date") else datetime.max.replace(tzinfo=timezone.utc), reverse=True)
                    current_time = datetime.now(timezone.utc)
                    seconds = days * 24 * 60 * 60 

                    if name:
                        name = name.lower()
                        filtered = [
                            item for item in data
                            if name in item.get("name", "").lower() and item.get("clan_tag") == DEFAULT_CLAN_TAG
                            and item.get("activity_change_date")
                        ]
                    else:
                        filtered = [
                            item for item in data
                            if item.get("clan_tag") == DEFAULT_CLAN_TAG and item.get("activity_change_date")
                            and (current_time - datetime.fromisoformat(item["activity_change_date"])).total_seconds() <= seconds
                        ]
                    
                    if not filtered:
                        embed = discord.Embed(
                            title='Player Last Action',
                            color=discord.Color.dark_grey(),
                            description="No players matching search criteria"
                        )
                        embed.timestamp = datetime.now(timezone.utc)
                        await interaction.followup.send(embed=embed)
                        return

                    # Sort filtered list by time_difference or activity date if you want
                    lines = []
                    for item in filtered:
                        activity_date = datetime.fromisoformat(item["activity_change_date"])
                        time_difference = (current_time - activity_date).total_seconds()
                        time_string = format_seconds_to_time_string(time_difference)
                        lines.append(f'{item["name"]: <17} {time_string}')

                    # Chunk lines into multiple fields within 1024-char limits
                    chunks = []
                    current_chunk = ""

                    for line in lines:
                        line += "\n"
                        if len(current_chunk) + len(line) > MAX_EMBED_FIELD_LENGTH - 6:  # 6 chars for ``` wrapper
                            chunks.append(f"```{current_chunk}```")
                            current_chunk = line
                        else:
                            current_chunk += line

                    if current_chunk:
                        chunks.append(f"```{current_chunk}```")

                    # Send all chunks as embed fields
                    for i, chunk in enumerate(chunks):
                        embed = discord.Embed(
                            title=f'Player Last Action{" (cont.)" if i > 0 else ""}',
                            color=discord.Color.green(),
                            description=f"*Mostly accurate* :chart_with_upwards_trend: " + (f'(last {days} days)' if not name else '')
                        )
                        embed.timestamp = datetime.now(timezone.utc)
                        embed.add_field(name=f"Players ({len(filtered)})" if i == 0 else "\u200b", value=chunk, inline=False)
                        await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")


    @app_commands.command(name="raid", description="Provides the latest Clan Capital Raid")
    @app_commands.describe(clan_tag="The tag of the clan (optional)")
    async def clan_capital(self, interaction: discord.Interaction, clan_tag: str = DEFAULT_CLAN_TAG):
        await interaction.response.defer()
        url = f"{BASE_URL}/clashofclans/clan/{urllib.parse.quote(clan_tag)}/capitalraidseasons?limit=1"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Unable to fetch clan capital data")
                        return
                    
                    data = await resp.json()
                    if not data.get('items') or len(data['items']) == 0:
                        return interaction.followup.send(f"No capital raid data for clan {clan_tag}")
                    embed, _, _ = create_capital_raid_embed(data, clan_tag)

                    await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")
    
    @tasks.loop(seconds=300)
    async def send_weekly_raid_log(self):
        guild_id = GUILD_ID
        channel_id = CHANNEL_CLAN_CAPITAL
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        url = f"{BASE_URL}/clashofclans/clan/{urllib.parse.quote(DEFAULT_CLAN_TAG)}/capitalraidseasons?limit=1"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return
                    
                    data = await resp.json()
                    if not data.get('items') or len(data['items']) == 0:
                        return
                    embed, _, end_time = create_capital_raid_embed(data, DEFAULT_CLAN_TAG)

                    elapsed = seconds_since_coc_timestamp(end_time)

                    # Send end time 3 hours before
                    should_send_end = (
                        290 < elapsed < 3600 and end_time != self.last_sent_capital_end_time
                    )

                    if should_send_end:
                        await channel.send(embed=embed)
                        self.last_sent_capital_end_time = end_time

        except Exception as e:
            await channel.send(f"Error: {e}")
    
    @tasks.loop(seconds=120) # Clan caching is 2min
    async def check_membership_change(self):
        """
        Monitors and notifies the following events: Player joins, player leaves, role changes
        """
        guild_id = GUILD_ID
        channel_id = CHANNEL_GENERAL
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        encoded_tag = urllib.parse.quote(DEFAULT_CLAN_TAG)
        url = f"{COC_PROXY_URL}/clans/{encoded_tag}/members"

        # Mapping roles to an index for comparison (promotion/demotion)
        role_map = {
            "member": 0,
            "admin": 1,
            "coLeader": 2,
            "leader": 3,
        }

        role_display_map = {
            "member": "Member",
            "admin": "Elder",
            "coLeader": "Co-leader",
            "leader": "Supreme Leader",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=COC_PROXY_HEADERS) as resp:
                    if resp.status != 200:
                        return

                    data = (await resp.json()).get("items")
                    # We dont have previous state when starting up the bot so skip the first call
                    if not self.clan_members:
                        self.clan_members = data
                        return                    
                    
                    previous_tags = {member["tag"] for member in self.clan_members}
                    current_tags = {member["tag"] for member in data}

                    joined_tags = current_tags - previous_tags
                    left_tags = previous_tags - current_tags
                    common_tags = current_tags & previous_tags

                    current_members_by_tag = {member["tag"]: member for member in data}
                    previous_members_by_tag = {member["tag"]: member for member in self.clan_members}

                    for tag in joined_tags:
                        joined_member = current_members_by_tag[tag]
                        embed = discord.Embed(
                            title=f'Membership Update',
                            color=discord.Color.green(),
                            description=f"[{joined_member['name']}](https://www.ashwingur.com/ClashOfClans/player/{joined_member['tag'].replace('#','')}) joined [TheOrganisation](https://www.ashwingur.com/ClashOfClans/clan/220QP2GGU)")
                        embed.add_field(name="Trophies 🏆", value=str(joined_member["trophies"]))
                        embed.add_field(name="Builder Trophies 🏆", value=str(joined_member["builderBaseTrophies"]))
                        embed.add_field(name=f'Town Hall <:TH{joined_member["townHallLevel"]}:{townhall_map[joined_member["townHallLevel"]]}>', value=str(joined_member["townHallLevel"]))
                        embed.add_field(name="Exp Level", value=str(joined_member["expLevel"]))
                        embed.timestamp = datetime.now(timezone.utc)
                        embed.set_thumbnail(url=joined_member.get("league", {}).get("iconUrls", {}).get("small"))
                        await channel.send(embed=embed)

                    for tag in left_tags:
                        left_member = previous_members_by_tag[tag]
                        embed = discord.Embed(
                            title=f'Membership Update',
                            color=discord.Color.red(),
                            description=f"[{left_member['name']}](https://www.ashwingur.com/ClashOfClans/player/{left_member['tag'].replace('#','')}) left/kicked from [TheOrganisation](https://www.ashwingur.com/ClashOfClans/clan/220QP2GGU)")
                        embed.timestamp = datetime.now(timezone.utc)
                        await channel.send(embed=embed)
                    
                    for tag in common_tags:
                        old_role = previous_members_by_tag[tag]["role"]
                        new_role = current_members_by_tag[tag]["role"]
                        
                        if old_role != new_role:
                            old_role_index = role_map[old_role]
                            new_role_index = role_map[new_role]
                            
                            # Check if it's a promotion or demotion
                            if new_role_index > old_role_index:
                                change_type = "Promotion"
                                role_change = f"promoted to **{role_display_map[new_role]}**"
                            elif new_role_index < old_role_index:
                                change_type = "Demotion"
                                role_change = f"demoted to **{role_display_map[new_role]}**"
                            else:
                                continue  # No role change, just skip
                            
                            member = current_members_by_tag[tag]
                            embed = discord.Embed(
                                title=f'{change_type} - {member["name"]}',
                                color=discord.Color.orange(),
                                description=f"[{member['name']}](https://www.ashwingur.com/ClashOfClans/player/{member['tag'].replace('#','')}) has been {role_change}"
                            )
                            await channel.send(embed=embed)

                    self.clan_members = data


        except Exception as e:
            await channel.send(f"Error: {e}")

    @send_daily_war_status.before_loop
    async def before_send_war(self):
        await self.bot.wait_until_ready()

    @send_weekly_raid_log.before_loop
    async def before_send_raid(self):
        await self.bot.wait_until_ready()

    @check_membership_change.before_loop
    async def before_check_membership_change(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(ClashCommands(bot))
