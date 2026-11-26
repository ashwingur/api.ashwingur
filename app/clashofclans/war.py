"""
Pure helpers for working out a clan's current war (regular or CWL) and CWL standings.
No Flask or network access here, so it is easy to test with saved API responses.
"""
from datetime import datetime, timezone

COC_TIME_FORMAT = "%Y%m%dT%H%M%S.%fZ"

# Higher = more relevant when deciding which war is "current"
STATE_PRIORITY = {"inWar": 3, "preparation": 2, "warEnded": 1}

CWL_WIN_BONUS_STARS = 10


def parse_coc_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, COC_TIME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _epoch(value) -> float:
    dt = parse_coc_time(value)
    return dt.timestamp() if dt else 0.0


def orient_war(war: dict, clan_tag: str):
    """
    Return a shallow copy of `war` where `clan` is always `clan_tag`'s side,
    or None if that clan isn't in the war.
    """
    if not war:
        return None
    clan = war.get("clan") or {}
    opponent = war.get("opponent") or {}
    if clan.get("tag") == clan_tag:
        return dict(war)
    if opponent.get("tag") == clan_tag:
        oriented = dict(war)
        oriented["clan"], oriented["opponent"] = opponent, clan
        return oriented
    return None


def war_outcome(clan_side: dict, opponent_side: dict) -> str:
    """'win', 'lose' or 'draw' using CoC rules: stars, then destruction."""
    ours = (clan_side.get("stars", 0), clan_side.get("destructionPercentage", 0.0))
    theirs = (opponent_side.get("stars", 0), opponent_side.get("destructionPercentage", 0.0))
    if ours > theirs:
        return "win"
    if ours < theirs:
        return "lose"
    return "draw"


def cwl_war_tags(leaguegroup: dict):
    """[(round_number, war_tag), ...] for every scheduled CWL war (skips the '#0' placeholders)."""
    tags = []
    for round_number, round_ in enumerate((leaguegroup or {}).get("rounds") or [], start=1):
        for war_tag in round_.get("warTags") or []:
            if war_tag and war_tag != "#0":
                tags.append((round_number, war_tag))
    return tags


def pick_wars(clan_tag: str, regular_war: dict, cwl_wars: list):
    """
    Choose the clan's most relevant war across the regular war and all CWL wars.

    Priority is battle day > preparation > ended; ties go to the war that ends latest.
    This copes with the league group still being returned after CWL finishes
    (an ended CWL war must not hide a newer regular war) and with a league group
    that has no wars yet (signup/matchmaking).

    Returns (active_war, recently_ended_war):
      active_war         - the war to show, oriented so `clan` is ours, with `isCwl` set (or None)
      recently_ended_war - the latest ended war that isn't `active_war` (useful for CWL, where a
                           round ends at the same moment the next one starts), or None
    """
    candidates = []

    if regular_war and regular_war.get("state") in STATE_PRIORITY:
        oriented = orient_war(regular_war, clan_tag)
        if oriented:
            oriented["isCwl"] = False
            candidates.append(oriented)

    for war in cwl_wars or []:
        if war.get("state") not in STATE_PRIORITY:
            continue
        oriented = orient_war(war, clan_tag)
        if oriented:
            oriented["isCwl"] = True
            candidates.append(oriented)

    if not candidates:
        return None, None

    def rank(war):
        return (STATE_PRIORITY[war["state"]], _epoch(war.get("endTime")))

    active = max(candidates, key=rank)
    ended = [w for w in candidates if w["state"] == "warEnded" and w is not active]
    recently_ended = max(ended, key=lambda w: _epoch(w.get("endTime"))) if ended else None
    return active, recently_ended


def summarise_cwl(leaguegroup: dict, cwl_wars: list, clan_tag: str, active_war_tag: str = None):
    """
    Build CWL standings for the whole group plus our round-by-round results.
    Standings follow the in-game ranking: stars (+10 per war won), then destruction.
    """
    if not leaguegroup:
        return None

    wars_by_tag = {w.get("war_tag"): w for w in cwl_wars or [] if w.get("war_tag")}

    standings = {}
    for clan in leaguegroup.get("clans") or []:
        standings[clan["tag"]] = {
            "tag": clan["tag"],
            "name": clan.get("name"),
            "badge": (clan.get("badgeUrls") or {}).get("small"),
            "stars": 0,
            "bonus_stars": 0,
            "total_stars": 0,
            "destruction": 0.0,  # sum of each war's destruction %
            "wars": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
        }

    rounds = []
    current_round = None
    for round_number, war_tag in cwl_war_tags(leaguegroup):
        war = wars_by_tag.get(war_tag)
        if not war:
            continue
        state = war.get("state")
        sides = [war.get("clan") or {}, war.get("opponent") or {}]

        if state in ("inWar", "warEnded"):
            for side, other in (sides, sides[::-1]):
                row = standings.get(side.get("tag"))
                if not row:
                    continue
                row["stars"] += side.get("stars", 0)
                row["destruction"] += side.get("destructionPercentage", 0.0)
                row["wars"] += 1
                if state == "warEnded":
                    outcome = war_outcome(side, other)
                    if outcome == "win":
                        row["wins"] += 1
                        row["bonus_stars"] += CWL_WIN_BONUS_STARS
                    elif outcome == "lose":
                        row["losses"] += 1
                    else:
                        row["draws"] += 1

        oriented = orient_war(war, clan_tag)
        if oriented:
            if war_tag == active_war_tag:
                current_round = round_number
            ours, theirs = oriented["clan"], oriented["opponent"]
            rounds.append({
                "round": round_number,
                "war_tag": war_tag,
                "state": state,
                "team_size": war.get("teamSize"),
                "start_time": war.get("startTime"),
                "end_time": war.get("endTime"),
                "result": war_outcome(ours, theirs) if state == "warEnded" else None,
                "clan": {
                    "stars": ours.get("stars", 0),
                    "destruction": ours.get("destructionPercentage", 0.0),
                    "attacks": ours.get("attacks", 0),
                },
                "opponent": {
                    "tag": theirs.get("tag"),
                    "name": theirs.get("name"),
                    "badge": (theirs.get("badgeUrls") or {}).get("small"),
                    "stars": theirs.get("stars", 0),
                    "destruction": theirs.get("destructionPercentage", 0.0),
                    "attacks": theirs.get("attacks", 0),
                },
            })

    for row in standings.values():
        row["total_stars"] = row["stars"] + row["bonus_stars"]
        row["destruction"] = round(row["destruction"], 2)

    ranked = sorted(standings.values(), key=lambda r: (-r["total_stars"], -r["destruction"], r["name"] or ""))
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position

    return {
        "season": leaguegroup.get("season"),
        "state": leaguegroup.get("state"),
        "total_rounds": len(leaguegroup.get("rounds") or []),
        "current_round": current_round,
        "standings": ranked,
        "rounds": rounds,
    }


def summarise_clan(clan: dict):
    """The handful of clan fields the war board needs (keeps the payload small)."""
    if not clan:
        return None
    return {
        "tag": clan.get("tag"),
        "name": clan.get("name"),
        "badge": (clan.get("badgeUrls") or {}).get("medium") or (clan.get("badgeUrls") or {}).get("small"),
        "clanLevel": clan.get("clanLevel"),
        "isWarLogPublic": clan.get("isWarLogPublic"),
        "warWinStreak": clan.get("warWinStreak"),
        "warWins": clan.get("warWins"),
        "warLosses": clan.get("warLosses"),
        "warTies": clan.get("warTies"),
        "warLeague": (clan.get("warLeague") or {}).get("name"),
        "members": clan.get("members"),
    }
