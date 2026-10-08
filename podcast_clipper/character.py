"""Reaction character: an original 'Bean' mascot.

Renders 5 expression states as transparent PNGs into an asset folder so they're
easy to inspect and swap. Tone labels from highlight detection map onto these.
The art is original (simple geometric shapes) — no third-party IP.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Expression set and the tone -> expression mapping.
EXPRESSIONS = ["neutral", "laughing", "shocked", "thinking", "nodding"]
BUILTIN = "bean"  # the generated mascot; custom sets are user-supplied PNGs
TONE_TO_EXPRESSION = {
    "funny": "laughing",
    "shocking": "shocked",
    "intense": "shocked",
    "thoughtful": "thinking",
    "heartwarming": "nodding",
}
DEFAULT_EXPRESSION = "neutral"

# Palette (RGBA). Swap these to recolor the mascot.
GREEN = (52, 179, 107, 255)
OUT = (40, 48, 66, 255)
WHITE = (255, 255, 255, 255)
ACCENT = (52, 179, 107, 255)

_W, _H = 460, 700
_CX = 230
_EYE_Y, _EYE_DX = 255, 66
_MOUTH_Y = 352


def expression_for_tone(tone: str) -> str:
    return TONE_TO_EXPRESSION.get((tone or "").lower(), DEFAULT_EXPRESSION)


def _body(d: ImageDraw.ImageDraw) -> None:
    d.rounded_rectangle([30, 70, 430, 650], radius=200, fill=GREEN, outline=OUT, width=6)


def _eye_white(d, cx, cy, r=34):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE, outline=OUT, width=4)


def _pupil(d, cx, cy, r=15):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=OUT)


def _draw(expression: str) -> Image.Image:
    img = Image.new("RGBA", (_W, _H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _body(d)
    L, R, ey, my = _CX - _EYE_DX, _CX + _EYE_DX, _EYE_Y, _MOUTH_Y

    if expression == "laughing":
        for ex in (L, R):
            d.arc([ex - 34, ey - 30, ex + 34, ey + 30], 200, 340, fill=OUT, width=12)
        d.pieslice([_CX - 52, my - 40, _CX + 52, my + 44], 20, 160, fill=OUT)

    elif expression == "shocked":
        for ex in (L, R):
            _eye_white(d, ex, ey, 40)
            _pupil(d, ex, ey, 13)
        d.line([(L - 30, ey - 60), (L + 30, ey - 70)], fill=OUT, width=12)
        d.line([(R - 30, ey - 70), (R + 30, ey - 60)], fill=OUT, width=12)
        d.ellipse([_CX - 22, my - 26, _CX + 22, my + 32], fill=OUT)

    elif expression == "thinking":
        for ex in (L, R):
            _eye_white(d, ex, ey, 34)
            _pupil(d, ex + 6, ey - 14, 14)  # look up-and-aside
        d.line([(_CX - 34, my), (_CX + 34, my)], fill=OUT, width=12)
        d.ellipse([342, 150, 378, 186], fill=ACCENT, outline=OUT, width=3)  # thought dots
        d.ellipse([392, 104, 420, 132], fill=ACCENT, outline=OUT, width=3)

    elif expression == "nodding":
        for ex in (L, R):
            d.arc([ex - 32, ey - 24, ex + 32, ey + 28], 20, 160, fill=OUT, width=12)
        d.arc([_CX - 50, my - 34, _CX + 50, my + 38], 20, 160, fill=OUT, width=14)
        d.arc([80, 30, 140, 90], 200, 340, fill=ACCENT, width=10)   # motion ticks
        d.arc([320, 30, 380, 90], 200, 340, fill=ACCENT, width=10)

    else:  # neutral
        for ex in (L, R):
            _eye_white(d, ex, ey, 34)
            _pupil(d, ex, ey, 15)
        d.arc([_CX - 46, my - 30, _CX + 46, my + 30], 20, 160, fill=OUT, width=12)

    return img


def ensure_assets(base_dir: Path, character_set: str = BUILTIN, force: bool = False) -> dict[str, Path]:
    """Generate (if missing) the built-in expression PNGs and return {expression: path}."""
    out_dir = base_dir / character_set
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for expr in EXPRESSIONS:
        p = out_dir / f"{expr}.png"
        if force or not p.exists():
            _draw(expr).save(p)
        paths[expr] = p
    return paths


def resolve_assets(base_dir: Path, character_set: str) -> dict[str, Path]:
    """Map every expression to a PNG for the given set, with graceful fallback.

    - Built-in set: generated on demand.
    - Custom set: use whatever PNGs the user dropped in; missing expressions fall
      back to `neutral.png` (or the single image present). Returns {} if the folder
      has no usable images so the caller can skip the overlay.
    """
    if character_set == BUILTIN:
        return ensure_assets(base_dir, character_set)
    d = base_dir / character_set
    present = {e: d / f"{e}.png" for e in EXPRESSIONS if (d / f"{e}.png").exists()}
    if not present:
        return {}
    fallback = present.get("neutral") or next(iter(present.values()))
    return {e: present.get(e, fallback) for e in EXPRESSIONS}
