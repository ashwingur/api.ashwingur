"""
Clash of Clans slash commands and clan monitors (membership, clan settings, raid weekend).
War board + war announcements live in clash_war_board.py.
"""
import asyncio
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import discord
import matplotlib
from dateutil import parser
from discord import app_commands
from discord.ext import commands, tasks

matplotlib.use("Agg")  # headless; must be set before any figure is created
from matplotlib.figure import Figure  # noqa: E402

import coc_http  # noqa: E402
from clash_common import (  # noqa: E402
    CHANNEL_CLAN_CAPITAL, CHANNEL_GENERAL, CHANNEL_MEMBERSHIP, DEFAULT_CLAN_TAG, EMOJI_CAPITAL_GOLD,
    EMOJI_DISTRICT_HALL, EMOJI_RAID_MEDAL, EMOJI_RAID_SWORD, EMOJI_RAID_SWORDS, MAX_EMBED_DESCRIPTION,
    add_chunked_field, clan_url, code_safe, discord_ts, escape, format_coc_timestamp_to_day_month,
    format_seconds_to_time_string, hero_emoji, pad, player_link, player_url, role_name,
    role_rank, seconds_since_coc_timestamp, sort_heroes, strip_accents, th_emoji, truncate,
)
from clash_events import get_clash_events  # noqa: E402
from clash_war import cwl_embed  # noqa: E402
from clash_war_image import build_war_message  # noqa: E402

log = logging.getLogger("clash.commands")

VALID_TAG = re.compile(r"^#?[0289PYLQGRJCUV]{3,12}$")


class UserFacingError(Exception):
    """An error whose message is safe and useful to show to the user."""


# ---- Rendering helpers --------------------------------------------------------------------------

def render_table_png(title: str, columns: List[str], rows: List[list], header_colour: str, col_widths: List[float]) -> io.BytesIO:
    """Render a dark-themed table to PNG. Uses Figure directly (not pyplot) so it is safe off the main thread."""
    fig = Figure(figsize=(10, max(1.5, len(rows) * 0.4)), facecolor="#0E0E0E")
    ax = fig.add_subplot()
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=columns, cellLoc="center", loc="center", colWidths=col_widths)
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 1.2)
    for (row, _), cell in table.get_celld().items():
        if row == 0:
            cell.set_text_props(weight="bold", color="#FFFFFF")
            cell.set_facecolor(header_colour)
        else:
            cell.set_facecolor("#23272A" if row % 2 == 0 else "#131618")
            cell.set_text_props(color="#DCDDDE")
        cell.set_edgecolor("lightgray")
    ax.set_title(title, fontsize=16, pad=2, color="#FFFFFF")
    fig.tight_layout(rect=[0, 0, 1, 1])
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150, facecolor=fig.get_facecolor())
    buf.seek(0)
    return buf


def create_capital_raid_embed(data: dict, clan_tag: str):
    """Embed for the latest capital raid. Returns (embed, startTime, endTime)."""
    raid = data["items"][0]

    start_date = format_coc_timestamp_to_day_month(raid.get("startTime"))
    end_date = format_coc_timestamp_to_day_month(raid.get("endTime"))
    state = (raid.get("state") or "unknown").capitalize()

    embed = discord.Embed(
        title=f"Latest Capital Raid ({clan_tag})",
        colour=discord.Colour.green(),
        description=f"[{start_date} – {end_date} ({state})]({clan_url(clan_tag)}/ClanCapitalRaidSeasons)",
    )
    embed.add_field(name=f"Total Loot {EMOJI_CAPITAL_GOLD}", value=f"{raid.get('capitalTotalLoot', 0):,}")
    embed.add_field(name=f"Offensive Reward {EMOJI_RAID_MEDAL}", value=f"{raid.get('offensiveReward', 0):,}")
    embed.add_field(name=f"Defensive Reward {EMOJI_RAID_MEDAL}", value=f"{raid.get('defensiveReward', 0):,}")
    embed.add_field(name=f"Raids Completed {EMOJI_RAID_SWORDS}", value=str(raid.get("raidsCompleted", 0)))
    embed.add_field(name=f"Total Attacks {EMOJI_RAID_SWORD}", value=str(raid.get("totalAttacks", 0)))
    embed.add_field(name=f"Districts Destroyed {EMOJI_DISTRICT_HALL}", value=str(raid.get("enemyDistrictsDestroyed", 0)))

    members = sorted(raid.get("members") or [], key=lambda m: -m.get("capitalResourcesLooted", 0))
    lines = []
    for m in members:
        attack_limit = m.get("attackLimit", 5) + m.get("bonusAttackLimit", 1)
        attacks_info = f" ({m.get('attacks', 0)}/{attack_limit})" if m.get("attacks", 0) < attack_limit else ""
        lines.append(f"{pad(code_safe(m.get('name')), 17)} {m.get('capitalResourcesLooted', 0):,}{attacks_info}")
    if lines:
        add_chunked_field(embed, f"Players ({len(members)})", lines)

    return embed, raid.get("startTime"), raid.get("endTime")


def player_embed(data: dict, activity: Optional[dict]) -> discord.Embed:
    th = data.get("townHallLevel")
    embed = discord.Embed(
        title=truncate(f"{data.get('name', '?')}", 256),
        url=player_url(data.get("tag")),
        colour=discord.Colour.dark_gold(),
    )
    lines = [f"`{data.get('tag')}` · Level {data.get('expLevel', '?')}"]
    clan = data.get("clan")
    if clan:
        lines.append(f"{role_name(data.get('role'))} of [{escape(clan.get('name'))}]({clan_url(clan.get('tag'))})")
    else:
        lines.append("Not in a clan")
    if activity and activity.get("activity_change_date"):
        try:
            lines.append(f"Last seen active ~{discord_ts(datetime.fromisoformat(activity['activity_change_date']))}")
        except ValueError:
            pass
    embed.description = "\n".join(lines)

    league = data.get("leagueTier") or data.get("league") or {}
    league_icon = (league.get("iconUrls") or {}).get("small") or (league.get("iconUrls") or {}).get("medium")
    if league_icon:
        embed.set_thumbnail(url=league_icon)

    weapon = data.get("townHallWeaponLevel")
    embed.add_field(name="Town Hall", value=f"{th_emoji(th)} {th}" + (f" · ⚙️{weapon}" if weapon else ""))
    embed.add_field(name="Trophies", value=f"🏆 {data.get('trophies', 0):,}\nBest {data.get('bestTrophies', 0):,}"
                    + (f"\n{league.get('name')}" if league.get("name") else ""))
    embed.add_field(name="War", value=f"⭐ {data.get('warStars', 0):,} stars\n"
                    + ("✅ Opted in" if data.get("warPreference") == "in" else "❌ Opted out"))
    embed.add_field(name="Donations", value=f"📤 {data.get('donations', 0):,}\n📥 {data.get('donationsReceived', 0):,}")
    embed.add_field(name="Capital", value=f"{EMOJI_CAPITAL_GOLD} {data.get('clanCapitalContributions', 0):,}")
    if data.get("builderHallLevel"):
        embed.add_field(name="Builder Base", value=f"BH{data['builderHallLevel']}\n🏆 {data.get('builderBaseTrophies', 0):,}")

    heroes = sort_heroes(data.get("heroes"))
    for village, label in (("home", "Heroes"), ("builderBase", "Builder Heroes")):
        lines = []
        for hero in heroes:
            if hero.get("village", "home") != village:
                continue
            maxed = hero.get("maxLevel") and hero.get("level") == hero.get("maxLevel")
            lines.append(f"{hero_emoji(hero.get('name'))} {hero.get('level')}/{hero.get('maxLevel', '?')}{' ✅' if maxed else ''}")
        if lines:
            embed.add_field(name=label, value="\n".join(lines), inline=False)
    embed.timestamp = datetime.now(timezone.utc)
    return embed


# ---- Cog ----------------------------------------------------------------------------------------

class ClashCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_sent_capital_end_time = None
        self.clan_members: Optional[List[dict]] = None  # previous member list (with heroes) for diffs
        self.clan_data: Optional[dict] = None  # previous clan data for property diffs
        self.send_weekly_raid_log.start()
        self.monitor_clan.start()

    async def cog_unload(self):
        self.send_weekly_raid_log.cancel()
        self.monitor_clan.cancel()

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """One place to turn command failures into a friendly message (and log the real cause)."""
        original = getattr(error, "original", error)
        if isinstance(original, UserFacingError):
            message = str(original)
        elif isinstance(original, coc_http.ApiError):
            message = f"⚠️ {original.message}"
        else:
            log.error("Command /%s failed", interaction.command.name if interaction.command else "?", exc_info=original)
            message = "⚠️ Something went wrong running that command. It has been logged."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    # ---- helpers ----

    async def _send(self, channel_id: int, **kwargs):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            log.warning("Channel %s not found, dropping message", channel_id)
            return
        try:
            await channel.send(**kwargs)
        except discord.HTTPException:
            log.exception("Failed to send to channel %s", channel_id)

    def _resolve_player_tag(self, query: str) -> str:
        """Turn a player name (clan member) or tag into a tag."""
        query = (query or "").strip()
        if not query:
            raise UserFacingError("Please give a player name or tag.")
        if query.startswith("#"):
            return coc_http.normalise_tag(query)
        wanted = strip_accents(query)
        members = self.clan_members or []
        exact = [m for m in members if strip_accents(m.get("name")) == wanted]
        partial = [m for m in members if wanted in strip_accents(m.get("name"))]
        if exact or len(partial) == 1:
            return (exact or partial)[0]["tag"]
        if VALID_TAG.match(coc_http.normalise_tag(query)):
            return coc_http.normalise_tag(query)
        if partial:
            names = ", ".join(escape(m.get("name")) for m in partial[:10])
            raise UserFacingError(f"Multiple members match '{escape(query)}': {names}")
        raise UserFacingError(f"No clan member called '{escape(query)}'. Try their player tag instead.")

    async def member_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        wanted = strip_accents(current)
        members = sorted(self.clan_members or [], key=lambda m: strip_accents(m.get("name")))
        matches = [m for m in members if wanted in strip_accents(m.get("name"))][:25]
        return [app_commands.Choice(name=truncate(f"{m.get('name')} ({m.get('tag')})", 100), value=m["tag"]) for m in matches]

    async def member_name_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return [app_commands.Choice(name=c.name, value=c.name.rsplit(" (", 1)[0][:100])
                for c in await self.member_autocomplete(interaction, current)]

    # ---- war ----

    @app_commands.command(name="war", description="Current war status (regular or CWL)")
    @app_commands.describe(clan_tag="The tag of the clan (optional)")
    async def war(self, interaction: discord.Interaction, clan_tag: str = DEFAULT_CLAN_TAG):
        await interaction.response.defer()
        board = await coc_http.fetch_war_board(clan_tag)
        embeds, files, _ = await build_war_message(board)
        await interaction.followup.send(embeds=embeds, files=files)

    @app_commands.command(name="cwl", description="Clan War League standings and round results")
    @app_commands.describe(clan_tag="The tag of the clan (optional)")
    async def cwl(self, interaction: discord.Interaction, clan_tag: str = DEFAULT_CLAN_TAG):
        await interaction.response.defer()
        board = await coc_http.fetch_war_board(clan_tag)
        embed = cwl_embed(board)
        if embed is None:
            await interaction.followup.send("This clan isn't in Clan War League right now.")
            return
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.followup.send(embed=embed)

    # ---- player ----

    @app_commands.command(name="player", description="Show a player's profile, heroes and activity")
    @app_commands.describe(player="Clan member name or player tag")
    async def player(self, interaction: discord.Interaction, player: str):
        await interaction.response.defer()
        tag = self._resolve_player_tag(player)
        status, data = await coc_http.coc_get(f"/players/{coc_http.quote_tag(tag)}", expect_ok=False)
        if status == 404:
            raise UserFacingError(f"No player found with tag {tag}.")
        if status != 200 or not data:
            raise coc_http.ApiError(status, "Couldn't fetch that player from Clash of Clans right now.")
        _, activity = await coc_http.api_get(f"/clashofclans/players/{coc_http.quote_tag(tag)}", expect_ok=False)
        await interaction.followup.send(embed=player_embed(data, activity if isinstance(activity, dict) else None))

    @player.autocomplete("player")
    async def _player_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.member_autocomplete(interaction, current)

    # ---- events ----

    @app_commands.command(name="events", description="Check current and upcoming Clash of Clans events")
    async def events(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Event dates 📅", colour=discord.Colour.dark_magenta(),
                              description="Ongoing and upcoming COC events")
        for event in get_clash_events():
            remaining = event.get("time_remaining")
            when = event.get("datetime")
            if remaining is None or when is None:
                continue
            verb = "🟢 Ends" if event["ongoing"] else "🟡 Starts"
            embed.add_field(name=event["event"], inline=False,
                            value=f"{verb} in `{format_seconds_to_time_string(remaining.total_seconds())}` ({discord_ts(when, 'f')})")
        await interaction.response.send_message(embed=embed)

    # ---- activity ----

    @app_commands.command(name="activity", description="Check when clan members were last active")
    @app_commands.describe(days="Days ago to filter by (default = 5)", name="Player name, overrides days filter (optional)")
    async def activity(self, interaction: discord.Interaction, days: app_commands.Range[int, 1, 3650] = 5, name: Optional[str] = None):
        await interaction.response.defer()
        _, data = await coc_http.api_get("/clashofclans/players")
        now = datetime.now(timezone.utc)

        def active_at(item):
            try:
                return datetime.fromisoformat(item["activity_change_date"])
            except (KeyError, TypeError, ValueError):
                return None

        players = [p for p in data if p.get("clan_tag") == DEFAULT_CLAN_TAG and active_at(p)]
        if name:
            wanted = strip_accents(name)
            filtered = [p for p in players if wanted in strip_accents(p.get("name"))]
        else:
            filtered = [p for p in players if (now - active_at(p)).total_seconds() <= days * 86400]
        filtered.sort(key=active_at, reverse=True)

        if not filtered:
            embed = discord.Embed(title="Player Last Action", colour=discord.Colour.dark_grey(),
                                  description="No players matching search criteria")
            embed.timestamp = now
            await interaction.followup.send(embed=embed)
            return

        lines = [f"{pad(code_safe(p.get('name')), 17)} {format_seconds_to_time_string((now - active_at(p)).total_seconds())}"
                 for p in filtered]
        embed = discord.Embed(title="Player Last Action", colour=discord.Colour.green(),
                              description="*Mostly accurate* :chart_with_upwards_trend: " + ("" if name else f"(last {days} days)"))
        add_chunked_field(embed, f"Players ({len(filtered)})", lines, max_fields=5)
        embed.timestamp = now
        await interaction.followup.send(embed=embed)

    @activity.autocomplete("name")
    async def _activity_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.member_name_autocomplete(interaction, current)

    # ---- attack history ----

    async def _fetch_attack_history(self, clan_tag: str, player_tags: str, player_names: str, days: int):
        start_date = datetime.now(ZoneInfo("UTC")) - timedelta(days=days)
        query = urlencode({"player_tags": player_tags, "player_names": player_names, "start": start_date.isoformat()})
        status, data = await coc_http.api_get(
            f"/clashofclans/clan/{coc_http.quote_tag(clan_tag)}/warattackhistory?{query}", expect_ok=False)
        if status != 200:
            raise UserFacingError(f"Error: {(data or {}).get('error', 'Unable to fetch attack history')}")
        if not data:
            raise UserFacingError("No attack history found for the given criteria.")
        return data

    @app_commands.command(name="attack_history_summary", description="Get a summary of war attack history, including average stars.")
    @app_commands.describe(
        clan_tag="Optional: The tag of the clan to check",
        player_tags="Optional: Comma-separated player tags",
        player_names="Optional: Comma-separated player names",
        days="Optional: Days ago to search from (default = 90)",
        cwl_only="Optional: Only show CWL attacks (default = False)",
    )
    async def attack_history_summary(self, interaction: discord.Interaction, clan_tag: str = DEFAULT_CLAN_TAG,
                                     player_tags: str = "", player_names: str = "",
                                     days: app_commands.Range[int, 1, 3650] = 90, cwl_only: bool = False):
        await interaction.response.defer()
        data = await self._fetch_attack_history(clan_tag, player_tags, player_names, days)

        rows = []
        for player in data:
            attacks = [a for a in player.get("attacks") or [] if a.get("is_cwl") or not cwl_only]
            if not attacks and cwl_only:
                continue
            n = len(attacks) or 1
            rows.append({
                "name": player.get("name", "?"),
                "count": len(attacks),
                "stars": sum(a["stars"] for a in attacks) / n,
                "destruction": sum(a["destruction_percentage"] for a in attacks) / n,
                "duration": sum(a["duration"] for a in attacks) / n,
                "th_offset": sum(a["defender_townhall"] - a["attacker_townhall"] for a in attacks) / n,
                "pos_offset": sum(a["map_position"] - a["defender_map_position"] for a in attacks) / n,
            })
        if not rows:
            raise UserFacingError("No attack history found for the given criteria.")
        rows.sort(key=lambda r: (-r["stars"], -r["count"], r["name"]))

        table = [[r["name"], str(r["count"]), f"{r['stars']:.2f}", f"{r['destruction']:.2f}", f"{r['duration']:.1f}",
                  f"{r['th_offset']:.2f}", f"{r['pos_offset']:.2f}"] for r in rows]
        buf = await asyncio.to_thread(
            render_table_png,
            f'{"CWL " if cwl_only else ""}War Attack History Summary Averages ({days}D)',
            ["Name", "Attacks", "Stars", "Destruction", "Duration", "± Opponent TH", "± Opponent Pos."],
            table, "#6A340E", [0.15, 0.1, 0.1, 0.15, 0.15, 0.15, 0.15],
        )
        await interaction.followup.send(file=discord.File(buf, filename="attack_history_summary.png"))

    @app_commands.command(name="attack_history_logs", description="Get the attack history of a single player (limit 50)")
    @app_commands.describe(
        clan_tag="Optional: The tag of the clan to check",
        player_tag="Player tag",
        player_name="Player name",
        days="Optional: Days ago to search from (default = 90)",
        cwl_only="Optional: Only show CWL attacks (default = False)",
    )
    async def attack_history_logs(self, interaction: discord.Interaction, clan_tag: str = DEFAULT_CLAN_TAG,
                                  player_tag: str = "", player_name: str = "",
                                  days: app_commands.Range[int, 1, 3650] = 90, cwl_only: bool = False):
        await interaction.response.defer()
        if not player_tag and not player_name:
            raise UserFacingError("Please give a player_tag or player_name.")
        data = await self._fetch_attack_history(clan_tag, player_tag, player_name, days)
        player = data[0]

        sydney = ZoneInfo("Australia/Sydney")
        table = []
        for attack in (player.get("attacks") or [])[:50]:
            if cwl_only and not attack.get("is_cwl"):
                continue
            start = parser.parse(attack["start_timestamp"]).astimezone(sydney)
            table.append([start.strftime("%d-%m-%y"), attack["stars"], attack["destruction_percentage"], attack["duration"],
                          attack["attacker_townhall"], attack["defender_townhall"], attack["map_position"],
                          attack["defender_map_position"]])
        if not table:
            raise UserFacingError("No attack history found for the given criteria.")

        title = (f'{player.get("name", "?")} {"CWL " if cwl_only else ""}War Attack Logs ({days}D)\n'
                 f'All time war records: {player.get("all_time_regular_wars", 0)} regular wars, '
                 f'{player.get("all_time_cwl_wars", 0)} CWL wars')
        buf = await asyncio.to_thread(
            render_table_png, title,
            ["Date", "Stars", "Destruction", "Duration", "TH", "Opponent TH", "Pos.", "Opponent Pos."],
            table, "#07632D", [0.1, 0.08, 0.15, 0.15, 0.1, 0.15, 0.1, 0.15],
        )
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", player.get("name", "player"))
        await interaction.followup.send(file=discord.File(buf, filename=f"{safe_name}_attack_history_log.png"))

    @attack_history_logs.autocomplete("player_name")
    async def _attack_logs_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.member_name_autocomplete(interaction, current)

    # ---- capital raid ----

    @app_commands.command(name="raid", description="Provides the latest Clan Capital Raid")
    @app_commands.describe(clan_tag="The tag of the clan (optional)")
    async def clan_capital(self, interaction: discord.Interaction, clan_tag: str = DEFAULT_CLAN_TAG):
        await interaction.response.defer()
        tag = coc_http.normalise_tag(clan_tag)
        _, data = await coc_http.api_get(f"/clashofclans/clan/{coc_http.quote_tag(tag)}/capitalraidseasons?limit=1")
        if not data.get("items"):
            raise UserFacingError(f"No capital raid data for clan {tag}")
        embed, _, _ = create_capital_raid_embed(data, tag)
        await interaction.followup.send(embed=embed)

    @tasks.loop(seconds=300)
    async def send_weekly_raid_log(self):
        try:
            _, data = await coc_http.api_get(
                f"/clashofclans/clan/{coc_http.quote_tag(DEFAULT_CLAN_TAG)}/capitalraidseasons?limit=1")
            if not data.get("items"):
                return
            embed, _, end_time = create_capital_raid_embed(data, DEFAULT_CLAN_TAG)
            elapsed = seconds_since_coc_timestamp(end_time)
            # Post once, shortly after the raid weekend ends (results are final by then)
            if 290 < elapsed < 3600 and end_time != self.last_sent_capital_end_time:
                self.last_sent_capital_end_time = end_time
                await self._send(CHANNEL_CLAN_CAPITAL, embed=embed)
        except coc_http.ApiError as e:
            log.warning("Raid log fetch failed: %s", e.message)
        except Exception:
            log.exception("Raid log task failed")

    # ---- clan monitors ----

    @tasks.loop(seconds=120)  # clan endpoint caches for ~2 minutes
    async def monitor_clan(self):
        """Fetch the clan once and run every clan-level check on it."""
        try:
            _, clan = await coc_http.coc_get(f"/clans/{coc_http.quote_tag(DEFAULT_CLAN_TAG)}")
        except coc_http.ApiError as e:
            log.warning("Clan fetch failed: %s", e.message)
            return
        except Exception:
            log.exception("Clan fetch crashed")
            return

        for check in (self.check_membership_change, self.check_clan_properties_change):
            try:
                await check(clan)
            except Exception:
                log.exception("%s failed", check.__name__)

    async def _attach_heroes(self, members: List[dict]):
        """Add each member's heroes (needs a player call each). On failure keep the previous value."""
        previous = {m["tag"]: m for m in self.clan_members or []}
        semaphore = asyncio.Semaphore(5)

        async def fetch(member):
            async with semaphore:
                try:
                    status, data = await coc_http.coc_get(f"/players/{coc_http.quote_tag(member['tag'])}", expect_ok=False)
                    if status == 200 and isinstance(data, dict):
                        member["heroes"] = data.get("heroes") or []
                        return
                except coc_http.ApiError:
                    pass
            prev = previous.get(member["tag"])
            if prev and prev.get("heroes") is not None:
                member["heroes"] = prev["heroes"]

        await asyncio.gather(*(fetch(m) for m in members))

    async def check_membership_change(self, clan: dict):
        """Player joins/leaves, role changes, Town Hall upgrades, hero unlocks and maxed heroes."""
        members = clan.get("memberList") or []
        if not members:
            return  # never treat an empty/odd response as "everyone left"
        await self._attach_heroes(members)

        previous_list = self.clan_members
        # Update state before sending anything, so a send failure can't cause repeat announcements
        self.clan_members = members
        if previous_list is None:
            return  # first run after startup: nothing to compare against

        previous = {m["tag"]: m for m in previous_list}
        current = {m["tag"]: m for m in members}
        now = datetime.now(timezone.utc)
        clan_link = f"[{escape(clan.get('name', 'the clan'))}]({clan_url(clan.get('tag'))})"

        for tag in current.keys() - previous.keys():
            m = current[tag]
            embed = discord.Embed(title="Membership Update", colour=discord.Colour.green(),
                                  description=f"{player_link(m.get('name'), tag)} joined {clan_link}")
            embed.add_field(name="Trophies 🏆", value=str(m.get("trophies", "?")))
            embed.add_field(name="Builder Trophies 🏆", value=str(m.get("builderBaseTrophies", "?")))
            embed.add_field(name=f"Town Hall {th_emoji(m.get('townHallLevel'))}", value=str(m.get("townHallLevel", "?")))
            embed.add_field(name="Exp Level", value=str(m.get("expLevel", "?")))
            heroes = [f"{hero_emoji(h.get('name'))}`{h.get('level')}`" for h in sort_heroes(m.get("heroes"))
                      if h.get("village", "home") == "home"]
            embed.add_field(name="Heroes", value=" ".join(heroes) or "No heroes")
            embed.add_field(name="Clan Size", value=str(len(members)))
            league_icon = ((m.get("leagueTier") or {}).get("iconUrls") or {}).get("small")
            if league_icon:
                embed.set_thumbnail(url=league_icon)
            embed.timestamp = now
            await self._send(CHANNEL_MEMBERSHIP, embed=embed)

        for tag in previous.keys() - current.keys():
            m = previous[tag]
            embed = discord.Embed(title="Membership Update", colour=discord.Colour.red(),
                                  description=f"{player_link(m.get('name'), tag)} left/kicked from {clan_link}")
            embed.add_field(name="Clan Size", value=str(len(members)))
            embed.timestamp = now
            await self._send(CHANNEL_MEMBERSHIP, embed=embed)

        for tag in current.keys() & previous.keys():
            before, after = previous[tag], current[tag]
            link = player_link(after.get("name"), tag)

            old_role, new_role = before.get("role"), after.get("role")
            if old_role != new_role and role_rank(old_role) != role_rank(new_role):
                promoted = role_rank(new_role) > role_rank(old_role)
                embed = discord.Embed(
                    title=f"{'Promotion' if promoted else 'Demotion'} - {after.get('name')}",
                    colour=discord.Colour.orange() if promoted else discord.Colour.dark_red(),
                    description=f"{link} has been {'promoted' if promoted else 'demoted'} to **{role_name(new_role)}**")
                embed.timestamp = now
                await self._send(CHANNEL_GENERAL, embed=embed)

            old_th, new_th = before.get("townHallLevel") or 0, after.get("townHallLevel") or 0
            if new_th > old_th:
                embed = discord.Embed(title=f"Townhall Upgrade {th_emoji(new_th)}", colour=discord.Colour.blue(),
                                      description=f"{link} upgraded their Town Hall to **{new_th}**")
                embed.timestamp = now
                await self._send(CHANNEL_GENERAL, embed=embed)

            current_heroes, prev_heroes = after.get("heroes"), before.get("heroes")
            if current_heroes is None or prev_heroes is None:
                continue  # hero data unavailable for one of the snapshots; can't compare safely
            prev_by_name = {h.get("name"): h for h in prev_heroes}
            for hero in current_heroes:
                prev_hero = prev_by_name.get(hero.get("name"))
                display = hero_emoji(hero.get("name"))
                if prev_hero is None:
                    embed = discord.Embed(title="Hero Unlocked", colour=discord.Colour.gold(),
                                          description=f"{link} has unlocked the **{hero.get('name')}**! {display}")
                elif (hero.get("maxLevel") and prev_hero.get("level", 0) < hero["maxLevel"]
                      and hero.get("level") == hero["maxLevel"]):
                    embed = discord.Embed(title="Hero Maxed Out", colour=discord.Colour.gold(),
                                          description=f"{link} has maxed their **{hero.get('name')}**! {display}")
                    embed.add_field(name="Level", value=f"{hero['level']}/{hero['maxLevel']}")
                else:
                    continue
                embed.timestamp = now
                await self._send(CHANNEL_GENERAL, embed=embed)

    async def check_clan_properties_change(self, clan: dict):
        previous = self.clan_data
        self.clan_data = clan
        if previous is None:
            return

        def nested(data, *keys):
            for key in keys:
                data = (data or {}).get(key)
            return data

        changes = []
        simple = [
            ("Clan Type", ("type",)),
            ("Clan Location", ("location", "name")),
            ("Family Friendly", ("isFamilyFriendly",)),
            ("Clan Level", ("clanLevel",)),
            ("Clan Capital League", ("capitalLeague", "name")),
            ("Required Trophies", ("requiredTrophies",)),
            ("War Frequency", ("warFrequency",)),
            ("War Log Public", ("isWarLogPublic",)),
            ("War League", ("warLeague", "name")),
            ("Required Builder Base Trophies", ("requiredBuilderBaseTrophies",)),
            ("Chat Language", ("chatLanguage", "name")),
            ("Required Townhall Level", ("requiredTownhallLevel",)),
            ("Clan Capital Hall level", ("clanCapital", "capitalHallLevel")),
        ]
        for label, keys in simple:
            old, new = nested(previous, *keys), nested(clan, *keys)
            if old != new:
                changes.append(f"{label} changed from **{old if old is not None else 'N/A'}** to **{new if new is not None else 'N/A'}**")

        if previous.get("description") != clan.get("description"):
            old = code_safe(truncate(previous.get("description") or "N/A", 500))
            new = code_safe(truncate(clan.get("description") or "N/A", 500))
            changes.append(f"Clan Description changed:\nOld: ```{old}```\nNew: ```{new}```")

        badge_changed = nested(previous, "badgeUrls", "large") != nested(clan, "badgeUrls", "large")
        if badge_changed:
            changes.append("Clan Badge has changed!")

        prev_districts = {d["id"]: d for d in nested(previous, "clanCapital", "districts") or []}
        for district in nested(clan, "clanCapital", "districts") or []:
            prev = prev_districts.get(district["id"])
            name = district.get("name", "Unknown District")
            if prev is None:
                changes.append(f"New District '{name}' (Level: **{district.get('districtHallLevel', 'N/A')}**) added to Clan Capital.")
            elif prev.get("districtHallLevel") != district.get("districtHallLevel"):
                changes.append(f"District '{name}' levelled up from **{prev.get('districtHallLevel', 'N/A')}** "
                               f"to **{district.get('districtHallLevel', 'N/A')}**")

        prev_labels = {label["id"]: label["name"] for label in previous.get("labels") or []}
        curr_labels = {label["id"]: label["name"] for label in clan.get("labels") or []}
        for label_id, name in curr_labels.items():
            if label_id not in prev_labels:
                changes.append(f"New Label added: **{name}**.")
            elif prev_labels[label_id] != name:
                changes.append(f"Label '{prev_labels[label_id]}' changed name to **{name}**.")
        for label_id, name in prev_labels.items():
            if label_id not in curr_labels:
                changes.append(f"Label removed: **{name}**.")

        if not changes:
            return
        embed = discord.Embed(title="Clan Changes Detected", colour=discord.Colour.blue(),
                              description=truncate("\n".join(changes), MAX_EMBED_DESCRIPTION))
        if badge_changed and nested(clan, "badgeUrls", "small"):
            embed.set_thumbnail(url=nested(clan, "badgeUrls", "small"))
        embed.timestamp = datetime.now(timezone.utc)
        await self._send(CHANNEL_GENERAL, embed=embed)

    @send_weekly_raid_log.before_loop
    async def _before_raid(self):
        await self.bot.wait_until_ready()

    @monitor_clan.before_loop
    async def _before_monitor(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ClashCommands(bot))
