import json
import sys
import unicodedata
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
import aiohttp
import urllib.parse
from discord.ext import commands, tasks
import os
from typing import List, Tuple, Optional
from datetime import datetime, timedelta, timezone
from collections import Counter
from clash_events import get_clash_events
import matplotlib.pyplot as plt
import pandas as pd
import io
from dateutil import parser

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

def strip_accents(text):
    return ''.join(
        c for c in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(c)
    ).lower()

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
        self.clan_data = None # To store previous full clan data for other property checks
        self.send_daily_war_status.start()
        self.send_weekly_raid_log.start()
        self.check_membership_change.start()
        self.check_clan_properties_change.start() # Start the new loop for clan properties

    def cog_unload(self):
        self.send_daily_war_status.cancel()
        self.send_weekly_raid_log.cancel()
        self.check_membership_change.cancel()
        self.check_clan_properties_change.cancel() # Cancel the new task

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
                        return
                    embed = await create_clan_war_embed(data, clan_war, max_attacks)

                    await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(name="events", description="Check current and upcoming Clash of Clans events")
    async def events(self, interaction: discord.Interaction):
        events = get_clash_events()

        embed = discord.Embed(
            title=f"Event dates 📅",
            color=discord.Color.dark_magenta(),
            description=f"Ongoing and upcoming COC events"
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
                msg += f"🟡 Starts in `{format_seconds_to_time_string(time_remaining.total_seconds())}`"

            embed.add_field(name=name, value=msg, inline=False)

        await interaction.response.send_message(embed=embed)



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
                        prep_elapsed < 1800 and prep_time != self.last_sent_war_prep_time
                    )
                    # Send end time 3 hours before
                    should_send_end = (
                        elapsed > -10800 and end_time != self.last_sent_war_end_time
                    )

                    if should_send_prep or should_send_end:
                        if should_send_prep:
                            await channel.send("New war found!")
                            self.last_sent_war_prep_time = prep_time

                        if should_send_end:
                            await channel.send("War reminder")
                            self.last_sent_war_end_time = end_time
                        embed = await create_clan_war_embed(data, clan_war, max_attacks)
                        await channel.send(embed=embed)

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
                            if strip_accents(item.get("name", "")) and name in strip_accents(item.get("name", ""))
                            and item.get("clan_tag") == DEFAULT_CLAN_TAG
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

    @app_commands.command(name="attack_history_summary", description="Get a summary of war attack history, including average stars.")
    @app_commands.describe(
        clan_tag="Optional: The tag of the clan to check",
        player_tags="Optional: Comma-separated player tags",
        player_names="Optional: Comma-separated player names",
        days="Optional: Days ago to search from (default = 90)",
        cwl_only="Optional: Only show CWL attacks (default = False)"
    )
    async def attack_history_summary(
        self,
        interaction: discord.Interaction,
        clan_tag: str = DEFAULT_CLAN_TAG,
        player_tags: str = "",
        player_names: str = "",
        days: int = 90,
        cwl_only: bool = False
    ):
        """
        Retrieves and summarizes the war attack history for specified players or a clan,
        calculating the average stars, destruction, duration and opponent map position offset.
        """
        await interaction.response.defer()

        base_path = f"{BASE_URL}/clashofclans/clan/{urllib.parse.quote(clan_tag)}/warattackhistory"

        if days <= 0:
            days = 1
        elif days > 3650:
            days = 3650
        start_date = datetime.now(ZoneInfo("UTC")) - timedelta(days=days)

        query_params = urllib.parse.urlencode({
            "player_tags": player_tags,
            "player_names": player_names,
            "start": start_date.isoformat()
        })

        full_url = f"{base_path}?{query_params}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(full_url) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        await interaction.followup.send(f'Error: {data.get("error", "Unable to fetch attack history")}')
                        return
                    
                    if not data:
                        await interaction.followup.send("No attack history found for the given criteria.")
                        return


                    # --- PRE-PROCESS DATA TO CALCULATE AVERAGES AND ADD TO PLAYER DICTS ---
                    processed_players = []
                    for player in data:
                        total_stars = 0
                        total_duration = 0
                        total_destruction = 0
                        total_opponent_offset = 0
                        total_townhall_offset = 0
                        num_attacks = 0

                        for attack in player["attacks"]:
                            if cwl_only:
                                if not attack.get("is_cwl", False):
                                    continue
                            
                            num_attacks += 1
                            total_stars += attack["stars"]
                            total_duration += attack["duration"]
                            total_destruction += attack["destruction_percentage"]
                            total_opponent_offset += (attack["map_position"] - attack["defender_map_position"])
                            total_townhall_offset += (attack["defender_townhall"] - attack["attacker_townhall"])

                        # Handle division by zero if no attacks meet criteria
                        if num_attacks == 0:
                            if cwl_only: continue
                            average_stars = 0
                            average_duration = 0
                            average_destruction = 0
                            average_opponent_offset = 0
                            average_townhall_offset = 0
                        else:
                            average_stars = total_stars / num_attacks
                            average_duration = total_duration / num_attacks
                            average_destruction = total_destruction / num_attacks
                            average_opponent_offset = total_opponent_offset / num_attacks
                            average_townhall_offset = total_townhall_offset / num_attacks
                        
                        player['num_attacks'] = num_attacks
                        player['average_stars'] = average_stars
                        player['average_duration'] = average_duration
                        player['average_destruction'] = average_destruction
                        player['average_opponent_offset'] = average_opponent_offset
                        player['average_townhall_offset'] = average_townhall_offset
                        processed_players.append(player)
                    
                    
                    if not processed_players:
                        await interaction.followup.send("No attack history found for the given criteria.")
                        return

                    # --- SORTING BY AVERAGE STARS DESCENDING ---
                    sorted_players = sorted(processed_players, key=lambda p: (-p["average_stars"], -p["num_attacks"], p["name"]))

                    # Prepare data for the table from the sorted list
                    table_data = []
                    for player in sorted_players: # Iterate over the *sorted* players
                        table_data.append([
                            player['name'],
                            f"{player['num_attacks']}", # Use the filtered count
                            f"{player['average_stars']:.2f}",
                            f"{player['average_destruction']:.2f}",
                            f"{player['average_duration']:.1f}",
                            f"{player['average_townhall_offset']:.2f}",
                            f"{player['average_opponent_offset']:.2f}",
                        ])

                    # Create a DataFrame for easier table rendering
                    df = pd.DataFrame(table_data, columns=["Name", "Attacks", "Stars", "Destruction", "Duration", "± Opponent TH", "± Opponent Pos."])

                    # --- COLOR DEFINITIONS ---
                    BACKGROUND_COLOR = "#0E0E0E"
                    HEADER_BACKGROUND_COLOR = "#6A340E"
                    HEADER_TEXT_COLOR = "#FFFFFF"      
                    CELL_BACKGROUND_COLOR = "#23272A"  
                    CELL_TEXT_COLOR = "#DCDDDE"        

                    # Create the plot
                    fig, ax = plt.subplots(figsize=(10, max(1.5, len(df) * 0.4)), facecolor=BACKGROUND_COLOR) # Set figure background
                    ax.axis('off')

                    # Create the table
                    tbl = ax.table(cellText=df.values,
                                   colLabels=df.columns,
                                   cellLoc='center',
                                   loc='center',
                                   colWidths=[0.15, 0.1, 0.1, 0.15, 0.15, 0.15, 0.15]) # Adjust column widths

                    tbl.auto_set_font_size(False)
                    tbl.set_fontsize(10)
                    tbl.scale(1.2, 1.2) # Scale the table for better readability

                    # Style headers
                    for (row, col), cell in tbl.get_celld().items():
                        if row == 0:
                            cell.set_text_props(weight='bold', color=HEADER_TEXT_COLOR) # Apply header text color
                            cell.set_facecolor(HEADER_BACKGROUND_COLOR) # Apply header background color
                        else:
                            cell.set_facecolor(CELL_BACKGROUND_COLOR if row % 2 == 0 else "#131618")
                            cell.set_text_props(color=CELL_TEXT_COLOR) # Apply cell text color
                        cell.set_edgecolor('lightgray') # Cell borders

                    plt.title(f'{"CWL " if cwl_only else ""}War Attack History Summary Averages ({days}D)', fontsize=16, pad=2, color=HEADER_TEXT_COLOR) # Apply title text color
                    fig.tight_layout(rect=[0, 0, 1, 1]) # Adjust layout to prevent title overlap

                    # Save the plot to a BytesIO object
                    # Crucially, pass the facecolor of the figure to savefig to ensure the background is included
                    buf = io.BytesIO()
                    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150, facecolor=fig.get_facecolor())
                    buf.seek(0)
                    plt.close(fig)

                    # Send the image as a Discord File directly
                    file = discord.File(buf, filename="attack_history_summary.png")
                    await interaction.followup.send(file=file)

        except aiohttp.ClientError as e:
            await interaction.followup.send(f"Failed to connect to the API: {e}")
        except json.JSONDecodeError:
            await interaction.followup.send("Error: Could not parse response from the API.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}", file=sys.stderr)
            await interaction.followup.send(f"An unexpected error occurred: {e}")

    @app_commands.command(name="attack_history_logs", description="Get the attack history of a single player (limit 50)")
    @app_commands.describe(
        clan_tag="Optional: The tag of the clan to check",
        player_tag="Player tag",
        player_name="Player name",
        days="Optional: Days ago to search from (default = 30)",
        cwl_only="Optional: Only show CWL attacks (default = False)"
    )
    async def attack_history_logs(
        self,
        interaction: discord.Interaction,
        clan_tag: str = DEFAULT_CLAN_TAG,
        player_tag: str = "",
        player_name: str = "",
        days: int = 90,
        cwl_only: bool = False
    ):
        """
        Retrieves and summarizes the war attack history for specified players or a clan,
        calculating the average stars, destruction, duration and opponent map position offset.
        """
        await interaction.response.defer()

        base_path = f"{BASE_URL}/clashofclans/clan/{urllib.parse.quote(clan_tag)}/warattackhistory"

        if days <= 0:
            days = 1
        elif days > 3650:
            days = 3650
        start_date = datetime.now(ZoneInfo("UTC")) - timedelta(days=days)

        query_params = urllib.parse.urlencode({
            "player_tags": player_tag,
            "player_names": player_name,
            "start": start_date.isoformat()
        })

        full_url = f"{base_path}?{query_params}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(full_url) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        await interaction.followup.send(f'Error: {data.get("error", "Unable to fetch attack history")}')
                        return
                    
                    if not data:
                        await interaction.followup.send("No attack history found for the given criteria.")
                        return
                    
                    player = data[0]
                    table_data = []

                    for attack in player["attacks"][:50]:
                        if cwl_only:
                            if not attack.get("is_cwl", False):
                                continue
                        
                        # end_date = parser.parse(attack["war_end_timestamp"]).astimezone(ZoneInfo('Australia/Sydney'))
                        start_date = parser.parse(attack["start_timestamp"]).astimezone(ZoneInfo('Australia/Sydney'))
                        
                        table_data.append([
                            start_date.strftime('%d-%m-%y'),
                            attack["stars"],
                            attack["destruction_percentage"],
                            attack["duration"],
                            attack["attacker_townhall"],
                            attack["defender_townhall"],
                            attack["map_position"],
                            attack["defender_map_position"]
                        ])
                    if not table_data:
                        await interaction.followup.send("No attack history found for the given criteria.")
                        return

                    # Create a DataFrame for easier table rendering
                    df = pd.DataFrame(table_data, columns=["Date", "Stars", "Destruction", "Duration", "TH", "Opponent TH", "Pos.", "Opponent Pos."])

                    # --- COLOR DEFINITIONS ---
                    BACKGROUND_COLOR = "#0E0E0E"
                    HEADER_BACKGROUND_COLOR = "#07632D"
                    HEADER_TEXT_COLOR = "#FFFFFF"      
                    CELL_BACKGROUND_COLOR = "#23272A"  
                    CELL_TEXT_COLOR = "#DCDDDE"        

                    # Create the plot
                    fig, ax = plt.subplots(figsize=(10, max(1.5, len(df) * 0.4)), facecolor=BACKGROUND_COLOR) # Set figure background
                    ax.axis('off')

                    # Create the table
                    tbl = ax.table(cellText=df.values,
                                   colLabels=df.columns,
                                   cellLoc='center',
                                   loc='center',
                                   colWidths=[0.1, 0.08, 0.15, 0.15, 0.1, 0.15, 0.1, 0.15]) # Adjust column widths

                    tbl.auto_set_font_size(False)
                    tbl.set_fontsize(10)
                    tbl.scale(1.2, 1.2) # Scale the table for better readability

                    # Style headers
                    for (row, col), cell in tbl.get_celld().items():
                        if row == 0:
                            cell.set_text_props(weight='bold', color=HEADER_TEXT_COLOR) # Apply header text color
                            cell.set_facecolor(HEADER_BACKGROUND_COLOR) # Apply header background color
                        else:
                            cell.set_facecolor(CELL_BACKGROUND_COLOR if row % 2 == 0 else "#131618")
                            cell.set_text_props(color=CELL_TEXT_COLOR) # Apply cell text color
                        cell.set_edgecolor('lightgray') # Cell borders

                    plt.title(
                        f'{player["name"]} {"CWL " if cwl_only else ""}War Attack Logs ({days}D)\n'
                        f'All time war records: '
                        f'{player["all_time_regular_wars"]} regular wars, {player["all_time_cwl_wars"]} CWL wars',
                        fontsize=16,
                        pad=2,
                        color=HEADER_TEXT_COLOR
                    )
                    fig.tight_layout(rect=[0, 0, 1, 1]) # Adjust layout to prevent title overlap

                    # Save the plot to a BytesIO object
                    # Crucially, pass the facecolor of the figure to savefig to ensure the background is included
                    buf = io.BytesIO()
                    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150, facecolor=fig.get_facecolor())
                    buf.seek(0)
                    plt.close(fig)

                    # Send the image as a Discord File directly
                    file = discord.File(buf, filename=f"{player['name']}_attack_history_log.png")
                    await interaction.followup.send(file=file)

        except aiohttp.ClientError as e:
            await interaction.followup.send(f"Failed to connect to the API: {e}")
        except json.JSONDecodeError:
            await interaction.followup.send("Error: Could not parse response from the API.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}", file=sys.stderr)
            await interaction.followup.send(f"An unexpected error occurred: {e}")


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
            pass
            # await channel.send(f"Error: {e}")
    
    @tasks.loop(seconds=120) # Clan caching is 2min
    async def check_membership_change(self):
        """
        Monitors and notifies the following events: Player joins, player leaves, role changes, Town Hall upgrades.
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
        url = f"{COC_PROXY_URL}/clans/{encoded_tag}"

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

                    full_clan_data = await resp.json() # Fetch full data
                    current_member_list = full_clan_data.get("memberList")

                    # We don't have previous state when starting up the bot so skip the first call
                    if not self.clan_members:
                        self.clan_members = current_member_list
                        return

                    previous_tags = {member["tag"] for member in self.clan_members}
                    current_tags = {member["tag"] for member in current_member_list}

                    joined_tags = current_tags - previous_tags
                    left_tags = previous_tags - current_tags
                    common_tags = current_tags & previous_tags

                    current_members_by_tag = {member["tag"]: member for member in current_member_list}
                    previous_members_by_tag = {member["tag"]: member for member in self.clan_members}

                    # Handle joined members
                    for tag in joined_tags:
                        joined_member = current_members_by_tag[tag]
                        embed = discord.Embed(
                            title=f'Membership Update',
                            color=discord.Color.green(),
                            description=f"[{joined_member['name']}](https://www.ashwingur.com/ClashOfClans/player/{joined_member['tag'].replace('#','')}) joined [TheOrganisation](https://www.ashwingur.com/ClashOfClans/clan/220QP2GGU)")
                        embed.add_field(name="Trophies 🏆", value=str(joined_member["trophies"]))
                        embed.add_field(name="Builder Trophies 🏆", value=str(joined_member["builderBaseTrophies"]))
                        embed.add_field(name=f'Town Hall <:TH{joined_member["townHallLevel"]}:{townhall_map.get(joined_member["townHallLevel"], "unknown_emoji_id")}>', value=str(joined_member["townHallLevel"]))
                        embed.add_field(name="Exp Level", value=str(joined_member["expLevel"]))
                        embed.add_field(name="Clan Size", value=str(len(current_member_list)))
                        embed.timestamp = datetime.now(timezone.utc)
                        embed.set_thumbnail(url=joined_member.get("league", {}).get("iconUrls", {}).get("small"))
                        await channel.send(embed=embed)

                    # Handle left members
                    for tag in left_tags:
                        left_member = previous_members_by_tag[tag]
                        embed = discord.Embed(
                            title=f'Membership Update',
                            color=discord.Color.red(),
                            description=f"[{left_member['name']}](https://www.ashwingur.com/ClashOfClans/player/{left_member['tag'].replace('#','')}) left/kicked from [TheOrganisation](https://www.ashwingur.com/ClashOfClans/clan/220QP2GGU)")
                        embed.add_field(name="Clan Size", value=str(len(current_member_list)))
                        embed.timestamp = datetime.now(timezone.utc)
                        await channel.send(embed=embed)

                    # Handle role and Town Hall changes for common members
                    for tag in common_tags:
                        previous_member = previous_members_by_tag[tag]
                        current_member = current_members_by_tag[tag]

                        # Check for role changes
                        old_role = previous_member["role"]
                        new_role = current_member["role"]
                        
                        if old_role != new_role:
                            old_role_index = role_map[old_role]
                            new_role_index = role_map[new_role]
                            
                            if new_role_index > old_role_index:
                                change_type = "Promotion"
                                role_change = f"promoted to **{role_display_map[new_role]}**"
                                color = discord.Color.orange()
                            elif new_role_index < old_role_index:
                                change_type = "Demotion"
                                role_change = f"demoted to **{role_display_map[new_role]}**"
                                color = discord.Color.dark_red() # A darker red for demotion
                            else:
                                continue # Should not happen if old_role != new_role, but as a safeguard
                            
                            embed = discord.Embed(
                                title=f'{change_type} - {current_member["name"]}',
                                color=color,
                                description=f"[{current_member['name']}](https://www.ashwingur.com/ClashOfClans/player/{current_member['tag'].replace('#','')}) has been {role_change}"
                            )
                            embed.timestamp = datetime.now(timezone.utc)
                            await channel.send(embed=embed)

                        # Check for Town Hall level changes
                        old_th_level = previous_member["townHallLevel"]
                        new_th_level = current_member["townHallLevel"]


                        if new_th_level > old_th_level:
                            th_emoji_id = f'<:TH{new_th_level}:{townhall_map.get(new_th_level, "unknown_emoji_id")}>'
                            embed = discord.Embed(
                                title=f"Townhall Upgrade {th_emoji_id}",
                                color=discord.Color.blue(),
                                description=f"[{current_member['name']}](https://www.ashwingur.com/ClashOfClans/player/{current_member['tag'].replace('#','')}) upgraded their Town Hall to **{new_th_level}**"
                            )
                            await channel.send(embed=embed)
                    self.clan_members = current_member_list

        except aiohttp.ClientError as e:
            print(f"HTTP error fetching clan data: {e}")
        except Exception as e:
            print(f"An unexpected error occurred in check_membership_change: {e}", file=sys.stderr)
    


    @tasks.loop(seconds=120) # Clan caching is 2min
    async def check_clan_properties_change(self):
        """
        Monitors and notifies changes in various clan properties.
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
        url = f"{COC_PROXY_URL}/clans/{encoded_tag}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=COC_PROXY_HEADERS) as resp:
                    if resp.status != 200:
                        return

                    current_clan_data = await resp.json()

                    # Initialize clan_data on first run
                    if not self.clan_data:
                        self.clan_data = current_clan_data
                        return

                    previous_clan_data = self.clan_data
                    changes = []

                    # 1. Check 'type'
                    if current_clan_data.get("type") != previous_clan_data.get("type"):
                        changes.append(f"Clan Type changed from **{previous_clan_data.get('type', 'N/A')}** to **{current_clan_data.get('type', 'N/A')}**")

                    # 2. Check 'description'
                    if current_clan_data.get("description") != previous_clan_data.get("description"):
                        changes.append(f"Clan Description changed:\nOld: ```{previous_clan_data.get('description', 'N/A')}```\nNew: ```{current_clan_data.get('description', 'N/A')}```")

                    # 3. Check 'location' name
                    prev_location_name = previous_clan_data.get("location", {}).get("name")
                    curr_location_name = current_clan_data.get("location", {}).get("name")
                    if curr_location_name != prev_location_name:
                        changes.append(f"Clan Location changed from **{prev_location_name or 'N/A'}** to **{curr_location_name or 'N/A'}**")

                    # 4. Check 'isFamilyFriendly'
                    if current_clan_data.get("isFamilyFriendly") != previous_clan_data.get("isFamilyFriendly"):
                        changes.append(f"Clan Family Friendly status changed from **{previous_clan_data.get('isFamilyFriendly', 'N/A')}** to **{current_clan_data.get('isFamilyFriendly', 'N/A')}**")

                    # 5. Check 'badge' (just detect if badge URL changed)
                    prev_badge_url = previous_clan_data.get("badgeUrls", {}).get("large")
                    curr_badge_url = current_clan_data.get("badgeUrls", {}).get("large")
                    if curr_badge_url != prev_badge_url:
                        changes.append(f"Clan Badge has changed!")
                        embed.set_thumbnail(url=current_clan_data.get("badgeUrls", {}).get("small"))

                    # 6. Check 'clanLevel'
                    if current_clan_data.get("clanLevel") != previous_clan_data.get("clanLevel"):
                        changes.append(f"Clan Level changed from **{previous_clan_data.get('clanLevel', 'N/A')}** to **{current_clan_data.get('clanLevel', 'N/A')}**")

                    # 7. Check 'capitalLeague.name'
                    prev_capital_league = previous_clan_data.get("capitalLeague", {}).get("name")
                    curr_capital_league = current_clan_data.get("capitalLeague", {}).get("name")
                    if curr_capital_league != prev_capital_league:
                        changes.append(f"Clan Capital League changed from **{prev_capital_league or 'N/A'}** to **{curr_capital_league or 'N/A'}**")

                    # 8. Check 'requiredTrophies'
                    if current_clan_data.get("requiredTrophies") != previous_clan_data.get("requiredTrophies"):
                        changes.append(f"Required Trophies changed from **{previous_clan_data.get('requiredTrophies', 'N/A')}** to **{current_clan_data.get('requiredTrophies', 'N/A')}**")

                    # 9. Check 'warFrequency'
                    if current_clan_data.get("warFrequency") != previous_clan_data.get("warFrequency"):
                        changes.append(f"War Frequency changed from **{previous_clan_data.get('warFrequency', 'N/A')}** to **{current_clan_data.get('warFrequency', 'N/A')}**")

                    # 10. Check 'isWarLogPublic'
                    if current_clan_data.get("isWarLogPublic") != previous_clan_data.get("isWarLogPublic"):
                        changes.append(f"War Log Public status changed from **{previous_clan_data.get('isWarLogPublic', 'N/A')}** to **{current_clan_data.get('isWarLogPublic', 'N/A')}**")

                    # 11. Check 'warLeague.name'
                    prev_war_league = previous_clan_data.get("warLeague", {}).get("name")
                    curr_war_league = current_clan_data.get("warLeague", {}).get("name")
                    if curr_war_league != prev_war_league:
                        changes.append(f"War League changed from **{prev_war_league or 'N/A'}** to **{curr_war_league or 'N/A'}**")

                    # 12. Check 'requiredBuilderBaseTrophies'
                    prev_required_bb_trophies = previous_clan_data.get("requiredBuilderBaseTrophies")
                    curr_required_bb_trophies = current_clan_data.get("requiredBuilderBaseTrophies")
                    if curr_required_bb_trophies != prev_required_bb_trophies:
                        changes.append(f"Required Builder Base Trophies changed from **{prev_required_bb_trophies or 'N/A'}** to **{curr_required_bb_trophies or 'N/A'}**")

                    # 13. Check 'chatLanguage.name'
                    prev_chat_language = previous_clan_data.get("chatLanguage", {}).get("name")
                    curr_chat_language = current_clan_data.get("chatLanguage", {}).get("name")
                    if curr_chat_language != prev_chat_language:
                        changes.append(f"Chat Language changed from **{prev_chat_language or 'N/A'}** to **{curr_chat_language or 'N/A'}**")

                    # 14. Check 'requiredTownhallLevel'
                    prev_required_th_level = previous_clan_data.get("requiredTownhallLevel")
                    curr_required_th_level = current_clan_data.get("requiredTownhallLevel")
                    if curr_required_th_level != prev_required_th_level:
                        changes.append(f"Required Townhall Level changed from **{prev_required_th_level or 'N/A'}** to **{curr_required_th_level or 'N/A'}**")

                    # 15. Check 'clanCapital.capitalHallLevel'
                    prev_capital_hall_level = previous_clan_data.get("clanCapital", {}).get("capitalHallLevel")
                    curr_capital_hall_level = current_clan_data.get("clanCapital", {}).get("capitalHallLevel")
                    if curr_capital_hall_level != prev_capital_hall_level:
                        changes.append(f"Clan Capital Hall levelled up from **{prev_capital_hall_level or 'N/A'}** to **{curr_capital_hall_level or 'N/A'}**")

                    # 16. Check 'clanCapital.districts' (districtHallLevel changes)
                    prev_districts = {d["id"]: d for d in previous_clan_data.get("clanCapital", {}).get("districts", [])}
                    curr_districts = {d["id"]: d for d in current_clan_data.get("clanCapital", {}).get("districts", [])}

                    for district_id, curr_district in curr_districts.items():
                        if district_id in prev_districts:
                            prev_district = prev_districts[district_id]
                            if curr_district.get("districtHallLevel") != prev_district.get("districtHallLevel"):
                                changes.append(f"District '{curr_district.get('name', 'Unknown District')}' levelled up from **{prev_district.get('districtHallLevel', 'N/A')}** to **{curr_district.get('districtHallLevel', 'N/A')}**")
                        else:
                            # New district added (less common, but good to cover)
                            changes.append(f"New District '{curr_district.get('name', 'Unknown District')}' (Level: **{curr_district.get('districtHallLevel', 'N/A')}**) added to Clan Capital.")

                    # 17. Check 'labels' (name changes, additions, removals)
                    prev_labels = {label["id"]: label["name"] for label in previous_clan_data.get("labels", [])}
                    curr_labels = {label["id"]: label["name"] for label in current_clan_data.get("labels", [])}

                    # Check for changes in existing labels or new labels
                    for label_id, curr_label_name in curr_labels.items():
                        if label_id in prev_labels:
                            if curr_label_name != prev_labels[label_id]:
                                changes.append(f"Label '{prev_labels[label_id]}' changed name to **{curr_label_name}**.")
                        else:
                            changes.append(f"New Label added: **{curr_label_name}**.")

                    # Check for removed labels
                    for label_id, prev_label_name in prev_labels.items():
                        if label_id not in curr_labels:
                            changes.append(f"Label removed: **{prev_label_name}**.")

                    # Send notification if any changes were detected
                    if changes:
                        embed = discord.Embed(
                            title="Clan Changes Detected",
                            color=discord.Color.blue(),
                            description="\n".join(changes)
                        )
                        embed.timestamp = datetime.now(timezone.utc)
                        await channel.send(embed=embed)

                    # Update the stored clan data for the next check
                    self.clan_data = current_clan_data

        except Exception as e:
            # print(f"Error checking clan properties: {e}") # Log the error
            pass


    @send_daily_war_status.before_loop
    async def before_send_war(self):
        await self.bot.wait_until_ready()

    @send_weekly_raid_log.before_loop
    async def before_send_raid(self):
        await self.bot.wait_until_ready()

    @check_membership_change.before_loop
    async def before_check_membership_change(self):
        await self.bot.wait_until_ready()

    @check_clan_properties_change.before_loop
    async def before_check_clan_properties_change(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ClashCommands(bot))
