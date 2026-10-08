"""libass-free caption renderer.

Renders word-synced (karaoke) captions with Pillow and emits a transparent
overlay video (qtrle .mov with alpha) that ffmpeg composites over the clip.
Used when the local ffmpeg lacks libass. Visually equivalent to the .ass path:
the active word is highlighted in the accent colour, the rest are white, all
with a black outline.
"""
from __future__ import annotations

import math
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Config
from .transcribe import Word

CAPTION_FPS = 15  # overlay framerate; word highlight granularity

# Common macOS font locations, preferring bold weights for punchy captions.
_FONT_CANDIDATES: dict[str, list[str]] = {
    "arial": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
    "arial black": ["/System/Library/Fonts/Supplemental/Arial Black.ttf"],
    "helvetica": ["/System/Library/Fonts/Helvetica.ttc"],
}
_FALLBACK_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _resolve_font_path(name: str) -> str | None:
    p = Path(name)
    if p.suffix and p.exists():
        return str(p)
    for cand in _FONT_CANDIDATES.get(name.lower(), []) + _FALLBACK_FONTS:
        if Path(cand).exists():
            return cand
    return None


@lru_cache(maxsize=64)
def _font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _ass_color_to_rgba(s: str) -> tuple[int, int, int, int]:
    """ASS &HAABBGGRR (AA: 00=opaque) -> Pillow RGBA."""
    s = s.strip().lstrip("&").lstrip("Hh")
    s = s.zfill(8)[-8:]
    aa, bb, gg, rr = (int(s[i:i + 2], 16) for i in (0, 2, 4, 6))
    return (rr, gg, bb, 255 - aa)


def _group_words(words: list[Word], per_line: int, gap_break: float = 0.6) -> list[list[Word]]:
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur and (len(cur) >= per_line or (w.start - cur[-1].end) > gap_break):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def _line_width(font: ImageFont.FreeTypeFont, words: list[str]) -> float:
    space = font.getlength(" ")
    return sum(font.getlength(w) for w in words) + space * max(0, len(words) - 1)


def _fit_font(font_path: str | None, base_size: int, words: list[str], max_w: float) -> ImageFont.FreeTypeFont:
    """Largest size (down to 40px) whose single row fits max_w."""
    size = base_size
    while size > 40:
        f = _font(font_path, size)
        if _line_width(f, words) <= max_w:
            return f
        size -= 4
    return _font(font_path, 40)


def _render_line(
    texts: list[str], active: int, *, font: ImageFont.FreeTypeFont, cfg: Config,
    colors: dict[str, tuple[int, int, int, int]],
) -> bytes:
    img = Image.new("RGBA", (cfg.width, cfg.height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    space = font.getlength(" ")
    widths = [font.getlength(t) for t in texts]
    total = sum(widths) + space * max(0, len(texts) - 1)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    x = (cfg.width - total) / 2
    y = cfg.height - cfg.caption_margin_v - line_h / 2
    for i, t in enumerate(texts):
        fill = colors["primary"] if i == active else colors["secondary"]
        d.text((x, y), t, font=font, fill=fill,
               stroke_width=cfg.caption_outline, stroke_fill=colors["outline"])
        x += widths[i] + space
    return img.tobytes()


def render_overlay_video(words: list[Word], clip_start: float, clip_duration: float,
                         cfg: Config, out_path: Path) -> Path | None:
    rel = [Word(w.start - clip_start, w.end - clip_start, w.text.strip())
           for w in words if w.end - clip_start > 0 and w.text.strip()]
    if not rel:
        return None

    groups = _group_words(rel, cfg.caption_words_per_line)
    font_path = _resolve_font_path(cfg.caption_font)
    colors = {
        "primary": _ass_color_to_rgba(cfg.caption_primary_color),
        "secondary": _ass_color_to_rgba(cfg.caption_secondary_color),
        "outline": _ass_color_to_rgba(cfg.caption_outline_color),
    }
    max_w = cfg.width * 0.92

    # Per-group: choose a fitting font and a display window [start, end+tail].
    rendered: list[dict] = []
    for g in groups:
        texts = [w.text for w in g]
        font = _fit_font(font_path, cfg.caption_fontsize, texts, max_w)
        rendered.append({
            "words": g, "texts": texts, "font": font,
            "start": g[0].start, "end": g[-1].end + 0.15,
        })

    blank = Image.new("RGBA", (cfg.width, cfg.height), (0, 0, 0, 0)).tobytes()
    frame_cache: dict[tuple[int, int], bytes] = {}

    def frame_bytes(t: float) -> bytes:
        for gi, g in enumerate(rendered):
            if g["start"] <= t < g["end"]:
                active = 0
                for wi, w in enumerate(g["words"]):
                    if w.start <= t:
                        active = wi
                key = (gi, active)
                if key not in frame_cache:
                    frame_cache[key] = _render_line(
                        g["texts"], active, font=g["font"], cfg=cfg, colors=colors)
                return frame_cache[key]
        return blank

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{cfg.width}x{cfg.height}", "-r", str(CAPTION_FPS),
        "-i", "-",
        "-c:v", "qtrle", "-pix_fmt", "argb",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    n_frames = max(1, int(math.ceil(clip_duration * CAPTION_FPS)))
    try:
        for i in range(n_frames):
            proc.stdin.write(frame_bytes(i / CAPTION_FPS))
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="ignore")
    if proc.wait() != 0:
        raise RuntimeError("caption overlay encode failed:\n" + "\n".join(err.splitlines()[-15:]))
    return out_path


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    lines: list[str] = []
    cur = ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if not cur or font.getlength(trial) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_hook_image(text: str, cfg: Config, out_path: Path) -> Path | None:
    """Draw a persistent hook banner (rounded bar + bold text) near the top and
    save a full-frame transparent PNG to composite over the clip."""
    text = (text or "").strip()
    if not text:
        return None
    W, H = cfg.width, cfg.height
    font_path = _resolve_font_path(cfg.hook_font)
    max_w = W * cfg.hook_max_width_frac - 2 * 34  # minus horizontal padding

    size = cfg.hook_fontsize
    font = _font(font_path, size)
    lines = _wrap(text, font, max_w)
    while size > 30 and len(lines) > 3:  # shrink until it fits in <= 3 lines
        size -= 4
        font = _font(font_path, size)
        lines = _wrap(text, font, max_w)

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    pad_x, pad_y = 34, 18
    text_w = max(font.getlength(ln) for ln in lines)
    bar_w = min(W - 40, int(text_w + 2 * pad_x))
    bar_h = int(len(lines) * line_h + 2 * pad_y)
    bar_x = (W - bar_w) // 2
    bar_y = cfg.hook_margin_top

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = _ass_color_to_rgba(cfg.hook_bg_color)
    bg = (bg[0], bg[1], bg[2], int(max(0.0, min(1.0, cfg.hook_bg_opacity)) * 255))
    d.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=18, fill=bg)

    tc = _ass_color_to_rgba(cfg.hook_text_color)
    oc = _ass_color_to_rgba(cfg.caption_outline_color)
    y = bar_y + pad_y
    for ln in lines:
        x = (W - font.getlength(ln)) / 2
        d.text((x, y), ln, font=font, fill=tc, stroke_width=2, stroke_fill=oc)
        y += line_h
    img.save(out_path)
    return out_path
