"""
Renders a Clash-of-Clans-style war map: a banner with both clans' badges and the score, then our
island and theirs with every base, the stars taken on it and (for us) attacks remaining.

Art comes from, in order of preference:
  - files you drop in discord_bot/assets/ (Supercell fan kit, see assets/README.md)
  - official images the game API already serves (clan badges)
  - the server's TH emojis
  - simple drawn fallbacks, so a missing asset never breaks the board

Supercell assets are only scaled, never recoloured (Fan Content Policy). The policy's disclaimer is
left off because this bot only runs on a private server; add one back if the images are ever shared publicly.

`render_war_map(view)` fetches remote images (cached in memory), then draws in a worker thread.
"""
import asyncio
import io
import logging
import math
import os
import random
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import discord
from PIL import Image, ImageDraw, ImageFilter

import coc_http
from clash_common import TOWNHALL_EMOJI_IDS
from clash_text import draw_text, text_width
from clash_war import WarView, build_war_embeds

log = logging.getLogger("clash.warimage")

WAR_MAP_FILENAME = "war_map.png"
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# ---- Layout -------------------------------------------------------------------------------------
CELL_W, CELL_H = 200, 196
ICON = 96
MARGIN, ISLAND_PAD, ISLAND_GAP = 28, 26, 36
HEADER_H = 176
BADGE = 112

SEA_TOP, SEA_BOTTOM = (31, 111, 168), (18, 72, 120)
SAND, GRASS, GRASS_DARK = (232, 207, 138), (106, 176, 76), (88, 156, 62)
OUR_COLOUR, THEIR_COLOUR = (59, 130, 246), (220, 60, 60)
WOOD, WOOD_LIGHT, WOOD_DARK = (122, 78, 40), (150, 98, 52), (62, 36, 18)
GOLD, GOLD_EDGE, STAR_EMPTY, STAR_EMPTY_EDGE = (255, 210, 63), (138, 90, 0), (70, 88, 70), (40, 52, 40)
ORANGE, GREEN_OK, RED_MISS = (255, 170, 40), (120, 230, 120), (255, 110, 110)


# ---- Local assets (optional) --------------------------------------------------------------------

@lru_cache(maxsize=None)
def _local_image(*parts: str) -> Optional[Image.Image]:
    """Load assets/<parts...> (any of .png/.webp/.jpg) if present."""
    base = os.path.join(ASSET_DIR, *parts)
    for path in (base, base + ".png", base + ".webp", base + ".jpg"):
        if os.path.isfile(path):
            try:
                return Image.open(path).convert("RGBA")
            except Exception:
                log.exception("Bad asset %s", path)
    return None


def _fit(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((w, h), Image.LANCZOS)
    return img


# ---- Remote images (TH emojis, clan badges) -----------------------------------------------------
_remote_cache: Dict[str, Optional[bytes]] = {}


async def _fetch_images(urls) -> Dict[str, Optional[bytes]]:
    async def fetch(url):
        try:
            async with coc_http.session().get(url) as resp:
                _remote_cache[url] = await resp.read() if resp.status == 200 else None
        except Exception:
            log.warning("Could not fetch image %s", url)  # not cached, retried next render

    await asyncio.gather(*(fetch(u) for u in set(urls) if u and u not in _remote_cache))
    return {u: _remote_cache.get(u) for u in urls if u}


def _th_emoji_url(level) -> Optional[str]:
    emoji_id = TOWNHALL_EMOJI_IDS.get(level)
    return f"https://cdn.discordapp.com/emojis/{emoji_id}.png?size=128" if emoji_id else None


def _open(data: Optional[bytes]) -> Optional[Image.Image]:
    if not data:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def _th_image(level, remote) -> Image.Image:
    img = _local_image("townhalls", str(level)) or _open(remote.get(_th_emoji_url(level)))
    if img is not None:
        bbox = img.getchannel("A").point(lambda a: 255 if a > 10 else 0).getbbox()
        return _fit(img.crop(bbox) if bbox else img, ICON, ICON)  # trim transparent padding so it sits on the ground
    # Fallback for a level with no art yet (e.g. a brand new TH)
    img = Image.new("RGBA", (ICON, ICON), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 14, ICON - 6, ICON - 4), radius=16, fill=(150, 150, 160), outline=(70, 70, 80), width=4)
    draw_text(d, (ICON / 2, ICON / 2 + 16), f"TH{level or '?'}", 24)
    return img


# ---- Shapes -------------------------------------------------------------------------------------

def star_points(cx: float, cy: float, r: float) -> List[Tuple[float, float]]:
    pts = []
    for i in range(10):
        radius = r if i % 2 == 0 else r * 0.45
        angle = -math.pi / 2 + i * math.pi / 5
        pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return pts


def draw_star(img: Image.Image, cx, cy, r, filled: bool):
    asset = _local_image("stars", "full" if filled else "empty")
    if asset is not None:
        star = _fit(asset, int(r * 2.3), int(r * 2.3))
        img.alpha_composite(star, (int(cx - star.width / 2), int(cy - star.height / 2)))
        return
    ImageDraw.Draw(img).polygon(star_points(cx, cy, r), fill=GOLD if filled else STAR_EMPTY,
                                outline=GOLD_EDGE if filled else STAR_EMPTY_EDGE, width=3)


def draw_stars(img, cx, cy, earned: int, r: float = 15, gap: float = 34):
    for i in range(3):
        # middle star sits a little higher, like the in-game war map
        draw_star(img, cx + (i - 1) * gap, cy - (5 if i == 1 else 0), r + (2 if i == 1 else 0), i < earned)


def _background(width: int, height: int) -> Image.Image:
    asset = _local_image("background")
    if asset is not None:  # cover-crop the supplied background
        return _cover(asset, width, height)

    col = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        col.putpixel((0, y), tuple(int(SEA_TOP[i] + (SEA_BOTTOM[i] - SEA_TOP[i]) * t) for i in range(3)))
    img = col.resize((width, height)).convert("RGBA")
    d = ImageDraw.Draw(img)
    rng = random.Random(7)  # deterministic: same data -> same image -> no needless re-upload
    for _ in range(width * height // 9000):
        x, y = rng.uniform(0, width), rng.uniform(0, height)
        d.arc((x, y, x + 34, y + 12), 200, 340, fill=(90, 160, 210), width=3)
    return img


# ---- Drawing ------------------------------------------------------------------------------------

def _grid(n: int) -> Tuple[int, int]:
    cols = max(3, math.ceil(math.sqrt(n * 0.6)))
    return cols, max(1, math.ceil(n / cols))


def _cover(asset: Image.Image, width: int, height: int) -> Image.Image:
    """Scale and centre-crop an image to exactly fill width x height."""
    scale = max(width / asset.width, height / asset.height)
    scaled = asset.resize((math.ceil(asset.width * scale), math.ceil(asset.height * scale)), Image.LANCZOS)
    left, top = (scaled.width - width) // 2, (scaled.height - height) // 2
    return scaled.crop((left, top, left + width, top + height))


def _draw_island(img: Image.Image, box, colour, seed: int):
    x0, y0, x1, y1 = box
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x0 + 8, y0 + 12, x1 + 8, y1 + 12), radius=48, fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(10)))

    surface = _local_image("island")
    if surface is not None:
        # War map art (assets/island.*) clipped to the island shape, with the side's coloured border
        w, h = x1 - x0, y1 - y0
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=48, fill=255)
        img.paste(_cover(surface, w, h), (x0, y0), mask)
        ImageDraw.Draw(img).rounded_rectangle(box, radius=48, outline=colour, width=6)
        return

    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=48, fill=SAND, outline=colour, width=6)
    d.rounded_rectangle((x0 + 14, y0 + 14, x1 - 14, y1 - 14), radius=38, fill=GRASS)
    rng = random.Random(seed)
    for _ in range(int((x1 - x0) * (y1 - y0) / 2500)):
        cx, cy = rng.uniform(x0 + 30, x1 - 30), rng.uniform(y0 + 30, y1 - 30)
        r = rng.uniform(4, 11)
        d.ellipse((cx - r, cy - r * 0.6, cx + r, cy + r * 0.6), fill=GRASS_DARK)


@lru_cache(maxsize=64)
def _ground_shadow(width: int) -> Image.Image:
    """Soft shadow sized to a building's footprint (translucent, so it suits any island surface)."""
    w, h = int(width * 1.1), int(width * 0.42)
    shadow = Image.new("RGBA", (w + 24, h + 24), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((12, 12, 12 + w, 12 + h), fill=(30, 18, 4, 120))
    return shadow.filter(ImageFilter.GaussianBlur(7))


def _draw_base(img, cx, top, member, pos, view: WarView, ours: bool, remote):
    """One base: stars on top, TH image, '#. name', then a status line."""
    d = ImageDraw.Draw(img)
    tag = member.get("tag")
    battle = view.state != "preparation"

    earned, pct = 0, None
    if battle:
        if ours:
            best = member.get("bestOpponentAttack") or {}
            earned, pct = best.get("stars", 0), best.get("destructionPercentage")
        else:
            earned = view.best_stars_on.get(tag, 0)
            pct = max((a.get("destructionPercentage", 0) for a in view.attacks if a.get("defenderTag") == tag), default=None)
        draw_stars(img, cx, top + 22, earned)

    icon = _th_image(member.get("townhallLevel"), remote)
    icon_top = top + 42
    icon_x, icon_y = int(cx - icon.width / 2), int(icon_top + (ICON - icon.height))
    # Shadow centred on the footprint (a little above the image's bottom edge), mostly hidden behind the building
    shadow = _ground_shadow(icon.width)
    footprint_y = icon_y + icon.height - icon.height * 0.16
    img.alpha_composite(shadow, (int(cx - shadow.width / 2), int(footprint_y - shadow.height / 2)))
    img.alpha_composite(icon, (icon_x, icon_y))

    d = ImageDraw.Draw(img)
    draw_text(d, (cx, icon_top + ICON + 28), member.get("name", "?"), 20, prefix=f"{pos}. ", max_width=CELL_W - 12)

    status_y = icon_top + ICON + 57
    if battle and ours:
        # Our attacks: '3★' per attack made, then a sword per attack left (broken once the war is over)
        items = []
        for a in sorted(member.get("attacks") or [], key=lambda a: a.get("order", 0)):
            items += [("text", str(a.get("stars", 0)), GREEN_OK), ("icon", _local_image("stars", "full"), "★", 18)]
        left = view.attacks_per_member - len(member.get("attacks") or [])
        ended = view.state == "warEnded"
        for _ in range(max(0, left)):
            items.append(("icon", _local_image("icons", "missed" if ended else "attack"), "✗" if ended else "⚔", 32))
        _draw_status_row(img, cx, status_y, items)
    elif battle and pct is not None:
        draw_text(d, (cx, status_y), f"{pct}%", 17)


def _draw_status_row(img: Image.Image, cx: float, baseline: float, items):
    """Draw a centred row of ('text', str, colour) and ('icon', image|None, fallback_text, size) items."""
    size, gap = 18, 6
    widths = []
    for item in items:
        if item[0] == "text" or item[1] is None:
            widths.append(text_width(item[1] if item[0] == "text" else item[2], size))
        else:
            widths.append(item[3])
    x = cx - (sum(widths) + gap * max(0, len(items) - 1)) / 2
    d = ImageDraw.Draw(img)
    for item, w in zip(items, widths):
        if item[0] == "text":
            draw_text(d, (x, baseline), item[1], size, fill=item[2], align="left")
        elif item[1] is None:
            draw_text(d, (x, baseline), item[2], size, fill=ORANGE, align="left")
        else:
            icon = _fit(item[1], item[3], item[3])
            # centre icons on the text's middle so mixed sizes line up
            img.alpha_composite(icon, (int(x + (w - icon.width) / 2), int(baseline - 7 - icon.height / 2)))
            d = ImageDraw.Draw(img)
        x += w + gap


def _draw_header(img: Image.Image, width: int, view: WarView, remote):
    d = ImageDraw.Draw(img)
    box = (MARGIN, MARGIN, width - MARGIN, MARGIN + HEADER_H - 20)
    d.rounded_rectangle((box[0] + 4, box[1] + 6, box[2] + 4, box[3] + 6), radius=26, fill=(0, 0, 0))
    d.rounded_rectangle(box, radius=26, fill=WOOD, outline=WOOD_DARK, width=5)
    d.rounded_rectangle((box[0] + 12, box[1] + 12, box[2] - 12, box[3] - 12), radius=18, fill=WOOD_LIGHT)
    mid = width / 2
    badge_y = int((box[1] + box[3]) / 2 - BADGE / 2)

    for ours, side in ((True, view.ours), (False, view.theirs)):
        badge = _open(remote.get(_badge_url(side)))
        badge_x = box[0] + 22 if ours else box[2] - 22 - BADGE
        if badge is not None:
            badge = _fit(badge, BADGE, BADGE)
            img.alpha_composite(badge, (badge_x + (BADGE - badge.width) // 2, badge_y + (BADGE - badge.height) // 2))

    d = ImageDraw.Draw(img)
    text_x_ours, text_x_theirs = box[0] + 22 + BADGE + 16, box[2] - 22 - BADGE - 16
    name_w = mid - text_x_ours - 150

    state = {"preparation": "PREPARATION DAY", "inWar": "BATTLE DAY"}.get(view.state, "")
    if view.state == "warEnded":
        state = {"win": "VICTORY!", "lose": "DEFEAT", "draw": "DRAW"}[view.outcome()]
    draw_text(d, (mid, box[1] + 44), state, 24, fill=(255, 230, 150))

    for ours, side in ((True, view.ours), (False, view.theirs)):
        x, align = (text_x_ours, "left") if ours else (text_x_theirs, "right")
        draw_text(d, (x, box[1] + 68), side.get("name", "?"), 34, fill=(190, 220, 255) if ours else (255, 200, 200),
                  align=align, max_width=name_w, stroke=4)
        if view.state != "preparation":
            line = f"{side.get('destructionPercentage', 0):.1f}%  ·  {side.get('attacks', 0)}/{view.max_attacks} attacks"
        else:
            line = f"{view.team_size} v {view.team_size}"
        draw_text(d, (x, box[1] + 116), line, 26, align=align, max_width=name_w)

    if view.state != "preparation":
        draw_star(img, mid, box[1] + 92, 30, True)
        d = ImageDraw.Draw(img)
        draw_text(d, (mid - 50, box[1] + 110), str(view.ours.get("stars", 0)), 48, align="right", stroke=5)
        draw_text(d, (mid + 50, box[1] + 110), str(view.theirs.get("stars", 0)), 48, align="left", stroke=5)
    else:
        draw_text(d, (mid, box[1] + 110), "VS", 44, stroke=5)


def _badge_url(side: dict) -> Optional[str]:
    badges = side.get("badgeUrls") or {}
    return badges.get("medium") or badges.get("large") or badges.get("small")


def draw_war_map(view: WarView, remote: Dict[str, Optional[bytes]]) -> bytes:
    n = max(len(view.our_members), len(view.their_members), 1)
    cols, rows = _grid(n)
    island_w = cols * CELL_W + CELL_W // 2 + 2 * ISLAND_PAD
    island_h = rows * CELL_H + 2 * ISLAND_PAD
    width = 2 * island_w + ISLAND_GAP + 2 * MARGIN
    islands_top = MARGIN + HEADER_H
    height = islands_top + island_h + MARGIN

    img = _background(width, height)
    _draw_header(img, width, view, remote)

    for ours, members, colour, x0 in (
        (True, view.our_members, OUR_COLOUR, MARGIN),
        (False, view.their_members, THEIR_COLOUR, MARGIN + island_w + ISLAND_GAP),
    ):
        _draw_island(img, (x0, islands_top, x0 + island_w, islands_top + island_h), colour, seed=1 if ours else 2)
        for i, member in enumerate(members):
            row, col = divmod(i, cols)
            # Zig-zag rows, like the in-game war map
            cx = x0 + ISLAND_PAD + CELL_W / 2 + col * CELL_W + (CELL_W / 2 if row % 2 else 0)
            top = islands_top + ISLAND_PAD + row * CELL_H
            _draw_base(img, cx, top, member, i + 1, view, ours, remote)


    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


async def render_war_map(view: WarView) -> Optional[bytes]:
    try:
        members = view.our_members + view.their_members
        urls = [_th_emoji_url(m.get("townhallLevel")) for m in members
                if _local_image("townhalls", str(m.get("townhallLevel"))) is None]
        urls += [_badge_url(view.ours), _badge_url(view.theirs)]
        remote = await _fetch_images([u for u in urls if u])
        return await asyncio.to_thread(draw_war_map, view, remote)
    except Exception:
        log.exception("War map render failed")
        return None


def war_map_file(png: bytes) -> discord.File:
    return discord.File(io.BytesIO(png), filename=WAR_MAP_FILENAME)


async def build_war_message(board: dict, live: bool = False):
    """Embeds + files for the board / /war. Falls back to the text battle map if the image fails."""
    png = await render_war_map(WarView(board["war"])) if board.get("war") else None
    embeds = build_war_embeds(board, live=live, war_map=f"attachment://{WAR_MAP_FILENAME}" if png else None)
    return embeds, ([war_map_file(png)] if png else []), png
