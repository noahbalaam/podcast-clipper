"""Load clips chosen by an outside agent (``--clips clips.json``).

Schema: a JSON list (or {"clips": [...]}) of objects:
    start     float seconds   (required)
    end       float seconds   (required)
    title     str             (required; used for the file name)
    hook      str             (optional; on-screen banner text — no banner if empty)
    caption   str             (optional; post caption, written to SUGGESTIONS.md)
    hashtags  [str]           (optional)
    reason    str             (optional)
    tone      str             (optional; funny|shocking|thoughtful|intense|heartwarming,
                               drives the reaction character; default thoughtful)

Invalid entries are skipped with a message instead of failing the run.
"""
from __future__ import annotations

import json
from pathlib import Path

from .highlights import TONES, Clip
from .transcribe import Transcript, Word

# Breathing room added around the snapped words (never into a neighbouring word).
PAD_START = 0.15
PAD_END = 0.25


def _snap(start: float, end: float, words: list[Word]) -> tuple[int, int] | None:
    """Indices (i, j) of the word whose start is nearest `start` and the word whose
    end is nearest `end`, so the cut never lands mid-word. None if they cross."""
    i = min(range(len(words)), key=lambda k: abs(words[k].start - start))
    j = min(range(len(words)), key=lambda k: abs(words[k].end - end))
    return (i, j) if j >= i else None


def load_agent_clips(path: str | Path, transcript: Transcript, min_s: float, max_s: float,
                     warn=print) -> tuple[list[Clip], list[str]]:
    """Return (valid clips sorted by start, list of skip messages)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("clips", [])
    if not isinstance(raw, list):
        raise ValueError("clips file must be a JSON list of clip objects (or {\"clips\": [...]})")

    words = transcript.all_words()
    if not words:
        raise ValueError("transcript has no word timestamps; cannot place clips")
    total = transcript.duration
    clips: list[Clip] = []
    skipped: list[str] = []

    def skip(n: int, why: str) -> None:
        msg = f"clip {n}: skipped — {why}"
        warn(f"  ! {msg}")
        skipped.append(msg)

    for n, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            skip(n, "not a JSON object"); continue
        try:
            start, end = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            skip(n, "missing or non-numeric start/end"); continue
        title = str(c.get("title") or "").strip()
        if not title:
            skip(n, "missing title"); continue
        if start < 0 or end <= start:
            skip(n, f"bad range {start:.1f}-{end:.1f}s (end must be after start)"); continue
        if total and start >= total:
            skip(n, f"starts at {start:.1f}s, past the transcribed audio ({total:.1f}s)"); continue

        idx = _snap(start, end, words)
        if idx is None:
            skip(n, f"no whole words between {start:.1f}s and {end:.1f}s"); continue
        i, j = idx
        s0, e0 = words[i].start, words[j].end
        dur = e0 - s0
        if dur < min_s - 0.01 or dur > max_s + 0.01:
            skip(n, f"'{title}' is {dur:.1f}s after snapping to word boundaries "
                    f"({s0:.2f}-{e0:.2f}s; requested {start:.2f}-{end:.2f}s), "
                    f"outside the allowed {min_s:g}-{max_s:g}s"); continue

        # Pad a little without eating into neighbouring words or breaking the limits.
        prev_end = words[i - 1].end if i > 0 else 0.0
        next_start = words[j + 1].start if j + 1 < len(words) else e0 + PAD_END
        room = max(0.0, max_s - dur)
        pad_s = min(PAD_START, max(0.0, s0 - prev_end), room)
        pad_e = min(PAD_END, max(0.0, next_start - e0), room - pad_s)
        s0, e0 = max(0.0, s0 - pad_s), e0 + pad_e

        hashtags = c.get("hashtags") or []
        if not isinstance(hashtags, list):
            hashtags = [str(hashtags)]
        tone = str(c.get("tone") or "thoughtful").lower()
        clips.append(Clip(
            start=s0, end=e0, title=title,
            hook=str(c.get("hook") or "").strip(),
            overlay_hook=str(c.get("hook") or "").strip(),
            caption=str(c.get("caption") or "").strip(),
            hashtags=[str(h) for h in hashtags],
            reason=str(c.get("reason") or "").strip(),
            tone=tone if tone in TONES else "thoughtful",
        ))

    clips.sort(key=lambda c: c.start)
    for a, b in zip(clips, clips[1:]):
        if b.start < a.end:
            warn(f"  ! warning: '{a.title}' and '{b.title}' overlap "
                 f"({b.start:.1f}s < {a.end:.1f}s) — cutting both anyway")
    return clips, skipped
