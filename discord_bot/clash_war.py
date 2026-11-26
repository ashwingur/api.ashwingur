"""
Embed builders for clan wars (regular + CWL). Pure functions of the /warboard API payload,
shared by the live war board, the /war and /cwl commands and the war announcements.
"""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import discord

from clash_common import (
    CHANNEL_WAR_BOARD, EMOJI_KNIGHT_CHEER, MAX_MESSAGE_EMBED_CHARS, add_chunked_field, clan_url, code_safe,
    discord_ts, escape, join_limited, pad, parse_coc_time, th_emoji, truncate,
)
from clash_events import get_clash_events

STARS_FULL, STARS_EMPTY = "★", "☆"
EMBED_BUDGET = MAX_MESSAGE_EMBED_CHARS - 300  # headroom for footer/timestamps


def stars_text(stars: int) -> str:
    stars = max(0, min(3, int(stars or 0)))
    return STARS_FULL * stars + STARS_EMPTY * (3 - stars)


class WarView:
    """A war (already oriented so `clan` is us) plus the derived stats the embeds need."""

    def __init__(self, war: dict):
        self.war = war
        self.state: str = war.get("state", "")
        self.is_cwl: bool = bool(war.get("isCwl"))
        self.cwl_round: Optional[int] = war.get("cwl_round")
        self.ours: dict = war.get("clan") or {}
        self.theirs: dict = war.get("opponent") or {}
        self.our_members = sorted(self.ours.get("members") or [], key=lambda m: m.get("mapPosition", 0))
        self.their_members = sorted(self.theirs.get("members") or [], key=lambda m: m.get("mapPosition", 0))
        self.team_size: int = war.get("teamSize") or max(len(self.our_members), len(self.their_members))
        self.attacks_per_member: int = war.get("attacksPerMember") or (1 if self.is_cwl else 2)
        self.prep_start = parse_coc_time(war.get("preparationStartTime"))
        self.start = parse_coc_time(war.get("startTime"))
        self.end = parse_coc_time(war.get("endTime"))

        our_tags = {m.get("tag") for m in self.our_members}
        self.members_by_tag: Dict[str, dict] = {m.get("tag"): m for m in self.our_members + self.their_members}
        # Display position = rank in the lineup (mapPosition can have gaps after the war starts)
        self.position: Dict[str, int] = {}
        for members in (self.our_members, self.their_members):
            for i, m in enumerate(members, start=1):
                self.position[m.get("tag")] = i

        # Every attack from both sides, in order, annotated with the new stars it gained.
        attacks = []
        for m in self.our_members + self.their_members:
            for a in m.get("attacks") or []:
                attacks.append({**a, "ours": m.get("tag") in our_tags})
        attacks.sort(key=lambda a: a.get("order", 0))
        best: Dict[str, int] = {}
        for a in attacks:
            prev = best.get(a.get("defenderTag"), 0)
            a["gain"] = max(0, a.get("stars", 0) - prev)
            best[a.get("defenderTag")] = max(prev, a.get("stars", 0))
        self.attacks = attacks
        self.best_stars_on: Dict[str, int] = best

    # ---- identity ----
    @property
    def war_id(self) -> int:
        """Stable id for this war (prep start time); used to de-duplicate announcements."""
        return int(self.prep_start.timestamp()) if self.prep_start else 0

    @property
    def our_name(self) -> str:
        return self.ours.get("name") or "Us"

    @property
    def their_name(self) -> str:
        return self.theirs.get("name") or "Opponent"

    # ---- stats ----
    @property
    def max_attacks(self) -> int:
        return self.team_size * self.attacks_per_member

    def outcome(self) -> str:
        ours = (self.ours.get("stars", 0), self.ours.get("destructionPercentage", 0.0))
        theirs = (self.theirs.get("stars", 0), self.theirs.get("destructionPercentage", 0.0))
        return "win" if ours > theirs else "lose" if ours < theirs else "draw"

    def three_stars(self, ours: bool) -> int:
        return sum(1 for a in self.attacks if a["ours"] == ours and a.get("stars") == 3)

    def attacks_left(self) -> List[Tuple[dict, int]]:
        """[(member, attacks remaining)] for our side, in lineup order."""
        out = []
        for m in self.our_members:
            left = self.attacks_per_member - len(m.get("attacks") or [])
            if left > 0:
                out.append((m, left))
        return out

    def member_totals(self) -> List[dict]:
        """Per-member totals for our side (stars gained, stars, destruction)."""
        totals = {m.get("tag"): {"member": m, "gain": 0, "stars": 0, "destruction": 0, "attacks": []}
                  for m in self.our_members}
        for a in self.attacks:
            t = totals.get(a.get("attackerTag"))
            if t:
                t["gain"] += a["gain"]
                t["stars"] += a.get("stars", 0)
                t["destruction"] += a.get("destructionPercentage", 0)
                t["attacks"].append(a)
        return list(totals.values())


# ---- shared bits --------------------------------------------------------------------------------

def _colour(view: WarView) -> discord.Colour:
    if view.state == "preparation":
        return discord.Colour.gold()
    outcome = view.outcome()
    if outcome == "win":
        return discord.Colour.green()
    if outcome == "lose":
        return discord.Colour.red()
    return discord.Colour.blurple() if view.state == "inWar" else discord.Colour.light_grey()


def _war_kind(view: WarView, board: dict) -> str:
    if view.is_cwl:
        total = (board.get("cwl") or {}).get("total_rounds") or 7
        return f"CWL Round {view.cwl_round}/{total}" if view.cwl_round else "Clan War League"
    return "Clan War"


def _status_line(view: WarView) -> str:
    if view.state == "preparation":
        return f"🟡 **Preparation day** · battle starts {discord_ts(view.start)} ({discord_ts(view.start, 't')})"
    if view.state == "inWar":
        return f"🔴 **Battle day** · ends {discord_ts(view.end)} ({discord_ts(view.end, 't')})"
    if view.state == "warEnded":
        return f"🏁 **War ended** {discord_ts(view.end)}"
    return f"State: {view.state or 'unknown'}"


def _score_line(view: WarView) -> Optional[str]:
    if view.state == "preparation":
        return None
    star_diff = view.ours.get("stars", 0) - view.theirs.get("stars", 0)
    pct_diff = view.ours.get("destructionPercentage", 0.0) - view.theirs.get("destructionPercentage", 0.0)
    if view.state == "warEnded":
        return {"win": "🏆 **Victory!**", "lose": "💀 **Defeat**", "draw": "🤝 **Draw**"}[view.outcome()]
    if star_diff > 0:
        return f"📈 Winning by **{star_diff}⭐**"
    if star_diff < 0:
        return f"📉 Losing by **{-star_diff}⭐**"
    if abs(pct_diff) < 0.005:
        return "⚖️ Dead even"
    return f"⚖️ Tied on stars, {'ahead' if pct_diff > 0 else 'behind'} by **{abs(pct_diff):.2f}%** destruction"


def _record_line(clan: Optional[dict]) -> Optional[str]:
    if not clan:
        return None
    parts = []
    streak = clan.get("warWinStreak")
    if isinstance(streak, int):
        flair = " 😂" if streak <= 5 else " 😮" if streak < 20 else " 😱" if streak < 50 else " 🐲"
        parts.append(f"🔥 {streak} streak{flair}")
    wins = clan.get("warWins")
    if isinstance(wins, int):
        losses, ties = clan.get("warLosses"), clan.get("warTies")
        record = f"{wins}W"
        if isinstance(losses, int):
            record += f" {losses}L {ties or 0}D"
        parts.append(record)
    return "\n".join(parts) or None


def _th_breakdown(members: List[dict]) -> str:
    counts = sorted(Counter(m.get("townhallLevel") for m in members if m.get("townhallLevel")).items(), reverse=True)
    return " ".join(f"{th_emoji(level)}×{count}" for level, count in counts) or "?"


def _side_summary(view: WarView, ours: bool, clan_info: Optional[dict]) -> str:
    side = view.ours if ours else view.theirs
    lines = []
    if view.state != "preparation":
        lines += [
            f"⭐ **{side.get('stars', 0)}** / {view.team_size * 3}",
            f"💥 {side.get('destructionPercentage', 0.0):.1f}%",
            f"⚔️ {side.get('attacks', 0)} / {view.max_attacks} attacks",
            f"🌟 {view.three_stars(ours)} triples",
        ]
    record = _record_line(clan_info)
    if record:
        lines.append(record)
    lines.append(_th_breakdown(view.our_members if ours else view.their_members))
    return truncate("\n".join(lines), 1024)


# ---- embeds -------------------------------------------------------------------------------------

def header_embed(board: dict, view: WarView) -> discord.Embed:
    our_clan = board.get("clan") or {}
    embed = discord.Embed(
        title=truncate(f"{view.our_name} vs {view.their_name}", 256),
        url=clan_url(view.ours.get("tag")),
        colour=_colour(view),
    )
    embed.set_author(name=f"{_war_kind(view, board)} · {view.team_size} v {view.team_size}",
                     icon_url=(view.ours.get("badgeUrls") or {}).get("small") or our_clan.get("badge"))
    opp_badge = (view.theirs.get("badgeUrls") or {}).get("medium") or (view.theirs.get("badgeUrls") or {}).get("small")
    if opp_badge:
        embed.set_thumbnail(url=opp_badge)

    lines = [_status_line(view)]
    score = _score_line(view)
    if score:
        lines.append(score)
    cwl = board.get("cwl")
    if view.is_cwl and cwl:
        league = cwl.get("league")
        lines.append(f"🏅 {league + ' · ' if league else ''}Season {cwl.get('season', '?')}")
    embed.description = "\n".join(lines)

    embed.add_field(name=truncate(view.our_name, 256), value=_side_summary(view, True, our_clan), inline=True)
    embed.add_field(name=truncate(view.their_name, 256), value=_side_summary(view, False, board.get("opponent_clan")), inline=True)

    if view.state == "inWar":
        left = view.attacks_left()
        if left:
            remaining = sum(n for _, n in left)
            names = [f"{escape(m.get('name'))}{f' ×{n}' if n > 1 else ''}" for m, n in left]
            embed.add_field(name=f"⏳ Attacks left · {len(left)} players, {remaining} attacks",
                            value=join_limited(names), inline=False)
        else:
            embed.add_field(name="⏳ Attacks left", value=f"Everyone has attacked! {EMOJI_KNIGHT_CHEER}", inline=False)
    elif view.state == "warEnded":
        missed = view.attacks_left()
        if missed:
            names = [f"{escape(m.get('name'))}{f' ×{n}' if n > 1 else ''}" for m, n in missed]
            embed.add_field(name=f"❌ Missed attacks · {sum(n for _, n in missed)}", value=join_limited(names), inline=False)
    return embed


def lineup_embed(view: WarView) -> discord.Embed:
    """Side-by-side lineup. In battle: our attacks (stars per attack) + best stars taken on the base opposite."""
    embed = discord.Embed(colour=_colour(view))
    rows = max(len(view.our_members), len(view.their_members))
    lines = []
    if view.state == "preparation":
        embed.title = "📋 Lineup"
        lines.append(" # TH Us          │ TH Them")
        for i in range(rows):
            ours = view.our_members[i] if i < len(view.our_members) else {}
            theirs = view.their_members[i] if i < len(view.their_members) else {}
            lines.append(f"{i + 1:>2} {ours.get('townhallLevel', ''):>2} {pad(code_safe(ours.get('name')), 11)} │ "
                         f"{theirs.get('townhallLevel', ''):>2} {code_safe(truncate(theirs.get('name') or '', 11))}")
    else:
        embed.title = "🎯 Battle map"
        embed.description = "Stars from each of our attacks (- = unused)"
        atk_width = max(3, view.attacks_per_member * 2 - 1)
        lines.append(f" # TH Member      {pad('Atk', atk_width)}")
        for i, ours in enumerate(view.our_members):
            done = [str(a.get("stars", 0)) for a in sorted(ours.get("attacks") or [], key=lambda a: a.get("order", 0))]
            atk = " ".join((done + ["-"] * view.attacks_per_member)[: max(view.attacks_per_member, len(done))])
            lines.append(f"{i + 1:>2} {ours.get('townhallLevel', ''):>2} {pad(code_safe(ours.get('name')), 11)} {atk}")
    add_chunked_field(embed, "​", lines)
    return embed


def cwl_embed(board: dict, show_rounds: bool = True) -> Optional[discord.Embed]:
    cwl = board.get("cwl")
    if not cwl or not cwl.get("standings"):
        return None
    our_tag = (board.get("clan") or {}).get("tag")
    title = f"🏅 CWL {cwl.get('season', '')}" + (f" · {cwl['league']}" if cwl.get("league") else "")
    embed = discord.Embed(title=title, colour=discord.Colour.purple())

    lines = ["  # Clan            ⭐  W-L  Dest"]
    for row in cwl["standings"]:
        marker = "▶" if row.get("tag") == our_tag else " "
        avg = row["destruction"] / row["wars"] if row.get("wars") else 0
        lines.append(f"{marker}{row.get('rank', '?'):>2} {pad(code_safe(row.get('name')), 15)} {row.get('total_stars', 0):>3} "
                     f"{row.get('wins', 0)}-{row.get('losses', 0):<2} {avg:4.0f}%")
    add_chunked_field(embed, "Standings (stars incl. +10 per win · avg destruction)", lines)

    if show_rounds and cwl.get("rounds"):
        round_lines = []
        for r in cwl["rounds"]:
            ours, theirs = r["clan"], r["opponent"]
            opp = escape(truncate(theirs.get("name"), 20))
            if r["state"] == "warEnded":
                icon = {"win": "✅", "lose": "❌", "draw": "➖"}.get(r.get("result"), "•")
                round_lines.append(f"`R{r['round']}` {icon} **{ours['stars']}-{theirs['stars']}** vs {opp} "
                                   f"({ours['destruction']:.0f}% - {theirs['destruction']:.0f}%)")
            elif r["state"] == "inWar":
                round_lines.append(f"`R{r['round']}` 🔴 {ours['stars']}-{theirs['stars']} vs {opp} · ends {discord_ts(parse_coc_time(r.get('end_time')))}")
            else:
                round_lines.append(f"`R{r['round']}` 🟡 vs {opp} · starts {discord_ts(parse_coc_time(r.get('start_time')))}")
        add_chunked_field(embed, "Our rounds", round_lines, code_block=False)
    return embed


def no_war_embed(board: dict) -> discord.Embed:
    clan = board.get("clan") or {}
    embed = discord.Embed(title=f"{clan.get('name', 'Clan')} · not in war", url=clan_url(clan.get("tag")),
                          colour=discord.Colour.dark_grey())
    if clan.get("badge"):
        embed.set_thumbnail(url=clan["badge"])

    lines = ["😴 No active war right now."]
    if board.get("war_log_private"):
        lines.append("🔒 The war log is private, so wars can't be tracked.")
    cwl = board.get("cwl")
    if cwl and cwl.get("state") == "preparation" and not cwl.get("rounds"):
        lines.append("🏅 CWL matchmaking is in progress.")
    embed.description = "\n".join(lines)

    last = board.get("last_war")
    if last:
        icon = {"win": "🏆 Win", "lose": "💀 Loss", "tie": "🤝 Draw"}.get(last.get("result"), "❔ Result unknown")
        ours, theirs = last.get("clan") or {}, last.get("opponent") or {}
        ended = parse_coc_time(last.get("endTime"))
        embed.add_field(name="Last war", inline=False, value=(
            f"{icon} vs **{escape(theirs.get('name', '?'))}** {discord_ts(ended) if ended else ''}\n"
            f"⭐ {ours.get('stars', '?')} - {theirs.get('stars', '?')} · "
            f"💥 {ours.get('destructionPercentage', 0):.1f}% - {theirs.get('destructionPercentage', 0):.1f}%"))

    record = _record_line(clan)
    if record or clan.get("warLeague"):
        embed.add_field(name="Record", value="\n".join(filter(None, [record, clan.get("warLeague")])), inline=False)

    events = []
    for event in get_clash_events():
        when = event.get("datetime")
        if not when:
            continue
        verb = "🟢 ends" if event["ongoing"] else "🟡 starts"
        events.append(f"**{event['event']}** {verb} {discord_ts(when)}")
    if events:
        embed.add_field(name="Events", value="\n".join(events), inline=False)
    return embed


def build_war_embeds(board: dict, live: bool = False, war_map: Optional[str] = None) -> List[discord.Embed]:
    """
    All embeds for the war board / /war command, trimmed to fit Discord's 6000-char message limit.
    war_map: URL of a rendered war map image (e.g. 'attachment://war_map.png'); it replaces the
    text battle map and is shown inside the header card.
    """
    war = board.get("war")
    if not war:
        embeds = [no_war_embed(board)]
    else:
        view = WarView(war)
        header = header_embed(board, view)
        cwl = cwl_embed(board, show_rounds=True) if view.is_cwl else None
        if war_map:
            header.set_image(url=war_map)
            lineup = discord.Embed()
            embeds = [e for e in (header, cwl) if e]
        else:
            lineup = lineup_embed(view)
            embeds = [e for e in (header, cwl, lineup) if e]
        if sum(len(e) for e in embeds) > EMBED_BUDGET and cwl:
            embeds.remove(cwl)
        while sum(len(e) for e in embeds) > EMBED_BUDGET and len(lineup.fields) > 1:
            lineup.remove_field(len(lineup.fields) - 1)

    footer = "Last updated" if live else "Updated"
    embeds[-1].set_footer(text=footer)
    embeds[-1].timestamp = datetime.now(timezone.utc)
    return embeds


def embeds_signature(embeds: List[discord.Embed]) -> str:
    """Hash of the embed content, ignoring the timestamp, to detect real changes."""
    payload = []
    for e in embeds:
        d = e.to_dict()
        d.pop("timestamp", None)
        payload.append(d)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# ---- announcements ------------------------------------------------------------------------------

def ref_footer(kind: str, view: WarView) -> str:
    """Footer marker used to avoid re-posting the same announcement after a restart."""
    return f"ref {kind}-{view.war_id}"


def new_war_embed(board: dict, view: WarView) -> discord.Embed:
    embed = header_embed(board, view)
    if view.state == "preparation":
        headline = f"⚔️ New {_war_kind(view, board)} found!"
    else:
        headline = f"⚔️ {_war_kind(view, board)} battle day has started!"
    embed.description = f"{headline}\n{embed.description}"
    if CHANNEL_WAR_BOARD:
        embed.description += f"\n📺 Live board: <#{CHANNEL_WAR_BOARD}>"
    embed.set_footer(text=ref_footer("new", view))
    return embed


def reminder_embed(board: dict, view: WarView) -> discord.Embed:
    left = view.attacks_left()
    embed = discord.Embed(
        title=f"⏰ War vs {view.their_name} ends soon",
        colour=discord.Colour.orange(),
        description="\n".join(filter(None, [
            f"Ends {discord_ts(view.end)} ({discord_ts(view.end, 't')})",
            _score_line(view),
            f"⭐ {view.ours.get('stars', 0)} - {view.theirs.get('stars', 0)} · "
            f"💥 {view.ours.get('destructionPercentage', 0):.1f}% - {view.theirs.get('destructionPercentage', 0):.1f}%",
        ])),
    )
    names = [f"{escape(m.get('name'))}{f' ×{n}' if n > 1 else ''}" for m, n in left]
    embed.add_field(name=f"⏳ Still to attack · {len(left)} players, {sum(n for _, n in left)} attacks",
                    value=join_limited(names) or "Nobody!", inline=False)
    if CHANNEL_WAR_BOARD:
        embed.add_field(name="​", value=f"📺 Live board: <#{CHANNEL_WAR_BOARD}>", inline=False)
    embed.set_footer(text=ref_footer("remind", view))
    return embed


def war_end_embed(board: dict, view: WarView) -> discord.Embed:
    outcome = view.outcome()
    title = {"win": f"🏆 Victory against {view.their_name}!",
             "lose": f"💀 Defeat against {view.their_name}",
             "draw": f"🤝 Draw with {view.their_name}"}[outcome]
    colour = {"win": discord.Colour.green(), "lose": discord.Colour.red(), "draw": discord.Colour.light_grey()}[outcome]
    embed = discord.Embed(title=truncate(title, 256), colour=colour, url=clan_url(view.ours.get("tag")))
    embed.set_author(name=f"{_war_kind(view, board)} · {view.team_size} v {view.team_size}",
                     icon_url=(view.ours.get("badgeUrls") or {}).get("small"))
    opp_badge = (view.theirs.get("badgeUrls") or {}).get("small")
    if opp_badge:
        embed.set_thumbnail(url=opp_badge)
    embed.description = (
        f"⭐ **{view.ours.get('stars', 0)}** - {view.theirs.get('stars', 0)} · "
        f"💥 {view.ours.get('destructionPercentage', 0):.2f}% - {view.theirs.get('destructionPercentage', 0):.2f}%\n"
        f"⚔️ {view.ours.get('attacks', 0)}/{view.max_attacks} attacks used · "
        f"🌟 {view.three_stars(True)} triples (they got {view.three_stars(False)})"
    )

    totals = [t for t in view.member_totals() if t["attacks"]]
    totals.sort(key=lambda t: (-t["gain"], -t["stars"], -t["destruction"]))
    if totals:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for medal, t in zip(medals, totals):
            attacks = ", ".join(f"{a.get('stars', 0)}★ {a.get('destructionPercentage', 0)}%" for a in t["attacks"])
            lines.append(f"{medal} **{escape(t['member'].get('name'))}** · +{t['gain']}⭐ ({attacks})")
        embed.add_field(name="Top attackers (by new stars gained)", value="\n".join(lines), inline=False)

    defenders = [m for m in view.our_members if (m.get("opponentAttacks") or 0) > 0
                 and (m.get("bestOpponentAttack") or {}).get("stars", 3) < 3]
    if defenders:
        best = max(defenders, key=lambda m: (m.get("opponentAttacks", 0), -(m.get("bestOpponentAttack") or {}).get("stars", 0)))
        held = (best.get("bestOpponentAttack") or {}).get("stars", 0)
        embed.add_field(name="🛡️ Best defence", inline=False,
                        value=f"**{escape(best.get('name'))}** held {best.get('opponentAttacks')} attack(s) to {held}⭐")

    missed = view.attacks_left()
    if missed:
        names = [f"{escape(m.get('name'))}{f' ×{n}' if n > 1 else ''}" for m, n in missed]
        embed.add_field(name=f"❌ Missed attacks · {sum(n for _, n in missed)}", value=join_limited(names), inline=False)

    cwl = board.get("cwl")
    our_tag = (board.get("clan") or {}).get("tag")
    if view.is_cwl and cwl:
        row = next((r for r in cwl.get("standings") or [] if r.get("tag") == our_tag), None)
        if row:
            embed.add_field(name="🏅 CWL standing", inline=False,
                            value=f"#{row['rank']} of {len(cwl['standings'])} · {row['total_stars']}⭐ · {row['wins']}W-{row['losses']}L")

    embed.set_footer(text=ref_footer("end", view))
    embed.timestamp = view.end or datetime.now(timezone.utc)
    return embed
