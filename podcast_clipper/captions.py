"""Generate an .ass subtitle file with word-synced (karaoke) highlighting.

Words fill from the 'secondary' colour to the 'primary' colour in time with
speech, using ASS \\k tags. One Dialogue line per small group of words.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .transcribe import Word


def _ass_time(seconds: float) -> str:
    """ASS uses H:MM:SS.cs (centiseconds)."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _group_words(words: list[Word], per_line: int, gap_break: float = 0.6) -> list[list[Word]]:
    """Chunk words into caption lines: cap at per_line, and break on long pauses."""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for i, w in enumerate(words):
        if cur:
            prev = cur[-1]
            if len(cur) >= per_line or (w.start - prev.end) > gap_break:
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[Word], clip_start: float, cfg: Config, out_path: Path) -> Path:
    """Write an .ass file for one clip. `words` carry absolute times; we rebase
    them to clip-relative (clip starts at 0)."""
    # Rebase to clip time and skip anything before the clip.
    rel = [Word(start=w.start - clip_start, end=w.end - clip_start, text=w.text)
           for w in words if w.end - clip_start > 0]

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {cfg.width}
PlayResY: {cfg.height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{cfg.caption_font},{cfg.caption_fontsize},{cfg.caption_primary_color},{cfg.caption_secondary_color},{cfg.caption_outline_color},&H64000000,-1,0,0,0,100,100,0,0,1,{cfg.caption_outline},2,2,80,80,{cfg.caption_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for group in _group_words(rel, cfg.caption_words_per_line):
        if not group:
            continue
        g_start = max(0.0, group[0].start)
        g_end = max(g_start + 0.1, group[-1].end)
        parts = []
        for i, w in enumerate(group):
            # \k duration tracks speech onset (gap until next word), in centiseconds.
            if i < len(group) - 1:
                dur = group[i + 1].start - w.start
            else:
                dur = w.end - w.start
            k = max(1, int(round(dur * 100)))
            parts.append(f"{{\\k{k}}}{_escape(w.text)}")
        text = "".join(parts).strip()
        lines.append(
            f"Dialogue: 0,{_ass_time(g_start)},{_ass_time(g_end)},Karaoke,,0,0,0,,{text}"
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
