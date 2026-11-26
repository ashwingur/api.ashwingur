"""
Multilingual text drawing for generated images (player and clan names can be in any script).

Pillow has no font fallback, so we do it ourselves:
  - fonts are searched in priority order: anything in assets/fonts/ (e.g. a fan-kit display
    font), then Noto Sans Bold + the per-script Noto fonts, CJK, symbols, and DejaVu as a last resort
  - each character uses the first font that has a glyph for it; spaces, digits, punctuation and
    combining marks stick to the surrounding run so words stay together
  - characters no font has (e.g. emoji) are dropped instead of drawn as boxes
  - right-to-left scripts (Arabic, Hebrew, ...) are shaped by raqm and the runs are put in visual
    order with a simplified bidi pass (one embedding level, which is enough for names)
"""
import glob
import logging
import os
import unicodedata
from functools import lru_cache
from typing import List, Optional, Tuple

import matplotlib
from PIL import ImageDraw, ImageFont, features

log = logging.getLogger("clash.text")

ASSET_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
NOTO_DIR = os.getenv("BOT_NOTO_DIR", "/usr/local/share/fonts/noto")

RAQM = features.check("raqm")
WHITE, BLACK = (255, 255, 255), (0, 0, 0)

RTL_CLASSES = {"R", "AL"}
STRONG_LTR = {"L"}
# Characters that take the font/direction of the run around them
NEUTRAL_CLASSES = {"WS", "ON", "CS", "ES", "ET", "EN", "AN", "BN", "NSM", "S", "B"}


def _font_paths() -> List[str]:
    paths = sorted(glob.glob(os.path.join(ASSET_FONT_DIR, "*.[ot]t[fc]")))  # user/fan-kit fonts first
    paths += [os.path.join(NOTO_DIR, "NotoSans-Bold.ttf")]
    paths += sorted(p for p in glob.glob(os.path.join(NOTO_DIR, "*.ttf")) if not p.endswith("/NotoSans-Bold.ttf"))
    paths += [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # CJK + Hangul
        os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans-Bold.ttf"),  # always available
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    seen, out = set(), []
    for p in paths:
        if p not in seen and os.path.exists(p):
            seen.add(p)
            out.append(p)
    return out


@lru_cache(maxsize=None)
def font_stack() -> Tuple[Tuple[str, frozenset], ...]:
    """(path, supported codepoints) for every usable font, in priority order."""
    from fontTools.ttLib import TTCollection, TTFont
    stack = []
    for path in _font_paths():
        try:
            font = TTCollection(path).fonts[0] if path.lower().endswith(".ttc") else TTFont(path, lazy=True)
            stack.append((path, frozenset(font.getBestCmap() or {})))
        except Exception:
            log.exception("Could not read font %s", path)
    if not RAQM:
        log.warning("Pillow has no raqm support: Arabic/Hebrew names won't be shaped correctly")
    return tuple(stack)


@lru_cache(maxsize=None)
def _cmap_by_path() -> dict:
    return dict(font_stack())


@lru_cache(maxsize=None)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC)


def _bidi(ch: str) -> str:
    return unicodedata.bidirectional(ch) or "L"


class Run:
    __slots__ = ("text", "path", "rtl")

    def __init__(self, text: str, path: str, rtl: bool):
        self.text, self.path, self.rtl = text, path, rtl


def _logical_runs(text: str) -> List[Run]:
    stack = font_stack()
    if not stack:
        return []
    runs: List[Run] = []
    for ch in text:
        cp = ord(ch)
        cls = _bidi(ch)
        if unicodedata.category(ch) in ("Cc", "Cf") and ch not in ("‍", "‌"):
            continue  # control/format chars (incl. stray bidi overrides)
        neutral = cls in NEUTRAL_CLASSES
        if neutral and runs and cp in _cmap_by_path()[runs[-1].path]:
            runs[-1].text += ch  # keep spaces/digits/marks with the current run
            continue
        path = next((p for p, cmap in stack if cp in cmap), None)
        if path is None:
            continue  # nobody can draw it (emoji etc.): drop it
        rtl = cls in RTL_CLASSES
        if runs and runs[-1].path == path and (runs[-1].rtl == rtl or neutral):
            runs[-1].text += ch
        else:
            if runs and neutral is False and rtl and not runs[-1].rtl and all(_bidi(c) in NEUTRAL_CLASSES for c in runs[-1].text):
                runs[-1].rtl = True  # a run of only neutrals before RTL text belongs to it
            runs.append(Run(ch, path, rtl))
    return runs


def _base_rtl(text: str) -> bool:
    for ch in text:
        cls = _bidi(ch)
        if cls in RTL_CLASSES:
            return True
        if cls in STRONG_LTR:
            return False
    return False


def _visual_runs(text: str) -> List[Run]:
    """Runs in left-to-right drawing order."""
    runs = _logical_runs(text)
    if not runs:
        return []
    # group adjacent runs of the same direction, then order the groups for the base direction
    groups: List[List[Run]] = []
    for run in runs:
        if groups and groups[-1][0].rtl == run.rtl:
            groups[-1].append(run)
        else:
            groups.append([run])
    if _base_rtl(text):
        groups.reverse()
    ordered: List[Run] = []
    for group in groups:
        ordered.extend(reversed(group) if group[0].rtl else group)
    return ordered


def _run_length(run: Run, size: int) -> float:
    font = _font(run.path, size)
    if RAQM:
        return font.getlength(run.text, direction="rtl" if run.rtl else "ltr")
    return font.getlength(run.text)


def text_width(text: str, size: int) -> float:
    return sum(_run_length(r, size) for r in _visual_runs(text))


def fit_text(text: str, size: int, max_width: float) -> str:
    """Trim (in logical order) and add an ellipsis until the text fits."""
    if text_width(text, size) <= max_width:
        return text
    while text and text_width(text + "…", size) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def draw_text(draw: ImageDraw.ImageDraw, xy, text: str, size: int, fill=WHITE, stroke: int = 3,
              align: str = "center", max_width: Optional[float] = None, prefix: str = ""):
    """
    Outlined text. xy = (x, baseline_y); align = left/center/right relative to x.
    prefix (e.g. '3. ') is always drawn on the left, even when the text is right-to-left.
    """
    prefix_w = text_width(prefix, size) if prefix else 0
    if max_width:
        text = fit_text(text, size, max_width - prefix_w)
    width = prefix_w + text_width(text, size)
    x = xy[0] - (width / 2 if align == "center" else width if align == "right" else 0)
    for part in ([prefix] if prefix else []) + [text]:
        for run in _visual_runs(part):
            font = _font(run.path, size)
            kwargs = {"direction": "rtl" if run.rtl else "ltr"} if RAQM else {}
            text_to_draw = run.text if RAQM or not run.rtl else run.text[::-1]
            draw.text((x, xy[1]), text_to_draw, font=font, fill=fill, anchor="ls",
                      stroke_width=stroke, stroke_fill=BLACK, **kwargs)
            x += _run_length(run, size)
