"""
Shared constants, emoji lookups and formatting helpers for the Clash of Clans cogs.

Robustness rule: every lookup of game data (town hall levels, heroes, roles, leagues)
must fall back to plain text. Supercell adds new levels/heroes regularly (e.g. TH19)
and a missing emoji should never crash a command or a background task.
"""
import os
import unicodedata
from datetime import datetime, timezone
from typing import Iterable, List, Optional

import discord

# ---- Server / clan configuration -------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


DEFAULT_CLAN_TAG = os.getenv("CLASH_CLAN_TAG", "#220QP2GGU")
GUILD_ID = _env_int("CLASH_GUILD_ID", 1081503290132545596)
CHANNEL_BOT = _env_int("CLASH_CHANNEL_BOT", 1089437682679165028)
CHANNEL_WAR = _env_int("CLASH_CHANNEL_WAR", 1081513755415949393)
CHANNEL_CLAN_CAPITAL = _env_int("CLASH_CHANNEL_CLAN_CAPITAL", 1081513938606362704)
CHANNEL_GENERAL = _env_int("CLASH_CHANNEL_GENERAL", 1081503290132545599)
CHANNEL_MEMBERSHIP = _env_int("CLASH_CHANNEL_MEMBERSHIP", 1412617696742211604)
# Read-only channel holding the single auto-updating war board message (0 = disabled)
CHANNEL_WAR_BOARD = _env_int("CLASH_WAR_BOARD_CHANNEL_ID", 1575308805422583979)

SITE_URL = "https://www.ashwingur.com/ClashOfClans"
MAX_EMBED_FIELD_LENGTH = 1024
MAX_EMBED_DESCRIPTION = 4096
MAX_MESSAGE_EMBED_CHARS = 6000

# ---- Emojis ------------------------------------------------------------------------------------

# Townhall emoji ids <:TH{level}:id>. Add new levels here; unknown levels fall back to "TH{n}".
TOWNHALL_EMOJI_IDS = {
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
    18: "1439929495548334201",
    19: "1575288126354497586",
}

HERO_EMOJIS = {
    "Barbarian King": "<:Barbarian_King:1393145179703083058>",
    "Archer Queen": "<:Archer_Queen:1393145176746229850>",
    "Minion Prince": "<:Minion_Prince:1393145181728936016>",
    "Grand Warden": "<:Grand_Warden:1393145174388904048>",
    "Royal Champion": "<:Royal_Champion:1393145172404994068>",
    "Dragon Duke": "<:Dragon_Duke:1480041568537804902>",
    "Battle Machine": "<:Battle_Machine:1393155805682995301>",
    "Battle Copter": "<:Battle_Copter:1393155803510345821>",
}

# Display order; unknown heroes go to the end (in the order the API returns them)
HERO_ORDER = list(HERO_EMOJIS)

EMOJI_CAPITAL_GOLD = "<:CapitalGold:1369496549138235402>"
EMOJI_RAID_MEDAL = "<:RaidMedal:1369496553445658735>"
EMOJI_RAID_SWORDS = "<:RaidSwords:1369496555194810448>"
EMOJI_RAID_SWORD = "<:RaidSwordSingle:1369496556859818034>"
EMOJI_DISTRICT_HALL = "<:DistrictHall:1369496551075872799>"
EMOJI_KNIGHT_CHEER = "<a:knightcheer:1369254948717723719>"

ROLE_RANK = {"member": 0, "admin": 1, "coLeader": 2, "leader": 3}
ROLE_NAMES = {"member": "Member", "admin": "Elder", "coLeader": "Co-leader", "leader": "Supreme Leader"}


def th_emoji(level) -> str:
    """Town hall emoji, or 'TH{n}' text if we don't have one for that level."""
    emoji_id = TOWNHALL_EMOJI_IDS.get(level)
    return f"<:TH{level}:{emoji_id}>" if emoji_id else f"TH{level}"


def hero_emoji(name: str) -> str:
    """Hero emoji, or the hero's name if we don't have one."""
    return HERO_EMOJIS.get(name) or name


def sort_heroes(heroes: Iterable[dict]) -> List[dict]:
    order = {name: i for i, name in enumerate(HERO_ORDER)}
    return sorted(heroes or [], key=lambda h: order.get(h.get("name"), len(order)))


def role_name(role: str) -> str:
    return ROLE_NAMES.get(role, (role or "Unknown").title())


def role_rank(role: str) -> int:
    return ROLE_RANK.get(role, 0)


# ---- Links -------------------------------------------------------------------------------------


def player_url(tag: str) -> str:
    return f"{SITE_URL}/player/{(tag or '').replace('#', '')}"


def clan_url(tag: str) -> str:
    return f"{SITE_URL}/clan/{(tag or '').replace('#', '')}"


def player_link(name: str, tag: str) -> str:
    return f"[{escape(name)}]({player_url(tag)})"


# ---- Time --------------------------------------------------------------------------------------


def parse_coc_time(value: Optional[str]) -> Optional[datetime]:
    """'20250505T092622.000Z' -> aware datetime (None if missing/invalid)."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def seconds_since_coc_timestamp(timestamp_str: str) -> float:
    dt = parse_coc_time(timestamp_str)
    if dt is None:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}")
    return (datetime.now(timezone.utc) - dt).total_seconds()


def discord_ts(dt: Optional[datetime], style: str = "R") -> str:
    """Discord timestamp markup; clients render it in local time and keep relative ones ticking."""
    if not dt:
        return "?"
    return f"<t:{int(dt.timestamp())}:{style}>"


def format_seconds_to_time_string(seconds: float) -> str:
    """Seconds -> 'Xd Yh Zm' (omits leading zero units, shows 1d 0h as 24h)."""
    total_minutes = int(seconds // 60)
    total_hours = int(total_minutes // 60)
    minutes = int(total_minutes % 60)
    days = int(total_hours // 24)
    hours = int(total_hours % 24)

    parts = []
    if days == 1 and hours == 0:
        parts.append("24h")
    else:
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0 or days > 0:
            parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def format_coc_timestamp_to_day_month(timestamp_str: str) -> str:
    dt = parse_coc_time(timestamp_str)
    return f"{dt.day} {dt.strftime('%b')}" if dt else "?"


# ---- Text --------------------------------------------------------------------------------------


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()


def escape(text) -> str:
    """Escape markdown in player/clan names (names like '__x__' or '*Bob*' break formatting)."""
    return discord.utils.escape_markdown(str(text or ""))


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    text = text or ""
    return text if len(text) <= limit else text[: max(0, limit - len(suffix))] + suffix


def code_safe(text: str) -> str:
    """Make text safe to put inside a ``` code block."""
    return (text or "").replace("`", "'")


def pad(text: str, width: int) -> str:
    """Left-align text in a fixed-width column, truncating if needed."""
    text = truncate(text or "", width, "…")
    return text + " " * (width - len(text))


def chunk_lines(lines: Iterable[str], limit: int = MAX_EMBED_FIELD_LENGTH, code_block: bool = True) -> List[str]:
    """Group lines into chunks that each fit in an embed field (optionally wrapped in ```)."""
    overhead = 6 if code_block else 0
    chunks, current = [], ""
    for line in lines:
        line = truncate(line, limit - overhead - 1) + "\n"
        if current and len(current) + len(line) > limit - overhead:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return [f"```{c}```" if code_block else c.rstrip("\n") for c in chunks]


def add_chunked_field(embed: discord.Embed, name: str, lines: Iterable[str], code_block: bool = True, max_fields: int = 6):
    """Add lines as one or more fields (continuations get an invisible name)."""
    chunks = chunk_lines(lines, code_block=code_block)
    for i, chunk in enumerate(chunks[:max_fields]):
        embed.add_field(name=name if i == 0 else "​", value=chunk, inline=False)


def join_limited(items: List[str], limit: int = MAX_EMBED_FIELD_LENGTH, sep: str = ", ") -> str:
    """Join items, ending with '+N more' if they don't all fit."""
    out: List[str] = []
    length = 0
    for i, item in enumerate(items):
        added = len(item) + (len(sep) if out else 0)
        remaining_after = len(items) - i - 1
        reserve = len(f"{sep}+{remaining_after} more") if remaining_after else 0
        if length + added + reserve > limit:
            more = f"+{len(items) - i} more"
            return sep.join(out + [more])
        out.append(item)
        length += added
    return sep.join(out)
