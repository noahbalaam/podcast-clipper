"""Pick candidate clips from a transcript.

Primary path: Claude with structured output (JSON schema).
Fallback path: a simple heuristic so the pipeline still runs without an API key.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import Config
from .transcribe import Transcript

TONES = ["funny", "shocking", "thoughtful", "intense", "heartwarming"]


@dataclass
class Clip:
    start: float
    end: float
    title: str
    hook: str
    tone: str
    hashtags: list[str] = field(default_factory=list)
    reason: str = ""
    overlay_hook: str = ""  # short punchy on-screen banner text

    @property
    def duration(self) -> float:
        return self.end - self.start


# JSON schema for structured output. Note: additionalProperties:false is required,
# and string/number constraints (minLength, minimum, ...) are intentionally omitted
# because structured outputs don't enforce them.
_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "Clip start time in seconds"},
                    "end": {"type": "number", "description": "Clip end time in seconds"},
                    "title": {"type": "string", "description": "Punchy 3-8 word title"},
                    "hook": {"type": "string", "description": "First-line hook to grab attention"},
                    "tone": {"type": "string", "enum": TONES},
                    "overlay_hook": {"type": "string",
                                     "description": "Punchy on-screen banner hook, max ~6 words"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string", "description": "Why this makes a strong short"},
                },
                "required": ["start", "end", "title", "hook", "tone", "overlay_hook", "hashtags", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def _system_prompt(cfg: Config) -> str:
    return (
        "You are an expert short-form video producer who finds the most viral, "
        "self-contained moments in long podcasts for YouTube Shorts, TikTok, and Reels.\n\n"
        f"Select exactly {cfg.num_clips} clips. Each clip MUST:\n"
        f"- be between {cfg.min_clip_seconds:.0f} and {cfg.max_clip_seconds:.0f} seconds long\n"
        "- be self-contained: start at a natural sentence boundary and end on a satisfying beat\n"
        "- have a strong hook in the first ~3 seconds\n"
        "- not overlap other selected clips\n\n"
        "Favor: strong hooks, stories with a payoff, hot takes, surprising facts, "
        "funny exchanges, emotional beats, and concrete actionable advice.\n\n"
        "For each clip set a 'tone' (one of: funny, shocking, thoughtful, intense, "
        "heartwarming) describing the dominant emotion — it will drive an on-screen "
        "reaction graphic.\n\n"
        "Also write an 'overlay_hook': a punchy on-screen banner of at most 6 words that "
        "makes a scroller stop and keep watching (curiosity gap, bold claim, or question). "
        "It must be short — not a full sentence — and different from 'title' and 'hook'.\n\n"
        "Use the [start-end] timestamps from the transcript to set start and end (in seconds)."
    )


def _pick_with_claude(transcript: Transcript, cfg: Config) -> list[Clip]:
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    user = (
        "Here is the timestamped transcript (times in seconds). Choose the best clips.\n\n"
        + transcript.transcript_for_prompt()
    )
    resp = client.messages.create(
        model=cfg.claude_model,
        max_tokens=cfg.claude_max_tokens,
        system=_system_prompt(cfg),
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    data = json.loads(text)
    clips = [
        Clip(
            start=float(c["start"]),
            end=float(c["end"]),
            title=c["title"],
            hook=c["hook"],
            tone=c["tone"] if c["tone"] in TONES else "thoughtful",
            hashtags=list(c.get("hashtags", [])),
            reason=c.get("reason", ""),
            overlay_hook=(c.get("overlay_hook") or c["title"]).strip(),
        )
        for c in data.get("clips", [])
    ]
    return clips


def _pick_heuristic(transcript: Transcript, cfg: Config) -> list[Clip]:
    """Evenly spaced windows across the episode; group whole segments to hit the
    target duration so cuts land on sentence boundaries."""
    segs = transcript.segments
    if not segs:
        return []
    target = (cfg.min_clip_seconds + cfg.max_clip_seconds) / 2
    total = transcript.duration
    clips: list[Clip] = []
    for i in range(cfg.num_clips):
        anchor = total * (i + 0.5) / cfg.num_clips
        # find first segment at/after the anchor
        start_idx = next((j for j, s in enumerate(segs) if s.start >= anchor), 0)
        start = segs[start_idx].start
        end = start
        j = start_idx
        while j < len(segs) and (end - start) < target:
            end = segs[j].end
            j += 1
        end = min(end, start + cfg.max_clip_seconds)
        if end - start < cfg.min_clip_seconds:
            end = min(start + cfg.min_clip_seconds, total)
        text = " ".join(s.text.strip() for s in segs[start_idx:max(start_idx + 1, j)])
        title = " ".join(text.split()[:8]) or f"Clip {i + 1}"
        clips.append(Clip(start=start, end=end, title=title, hook=title,
                          tone="thoughtful", hashtags=["#podcast", "#shorts"],
                          reason="Heuristic selection (no Claude).",
                          overlay_hook=" ".join(text.split()[:5]) or title))
    return clips


def _finalize(clips: list[Clip], transcript: Transcript, cfg: Config) -> list[Clip]:
    """Snap each clip to segment boundaries and enforce the [min, max] duration
    window: snap the start to the nearest segment start, then pick a segment end
    that lands within [start+min, start+max] and closest to Claude's intended end."""
    seg_starts = sorted(s.start for s in transcript.segments)
    seg_ends = sorted(s.end for s in transcript.segments)
    total = transcript.duration
    out: list[Clip] = []
    for c in clips:
        start = min(seg_starts, key=lambda x: abs(x - c.start)) if seg_starts else c.start
        start = max(0.0, start)
        lo, hi = start + cfg.min_clip_seconds, start + cfg.max_clip_seconds
        target = min(max(c.end, lo), hi)
        if total:
            target = min(target, total)
        # Prefer a segment end within the window and >= the minimum length.
        in_window = [e for e in seg_ends if start < e <= hi + 0.5]
        at_least_min = [e for e in in_window if e >= lo - 0.01]
        if at_least_min:
            end = min(at_least_min, key=lambda x: abs(x - target))
        elif in_window:
            end = max(in_window)  # best effort near the end of the episode
        else:
            end = target
        if total:
            end = min(end, total)
        if end - start < 1.0:
            continue
        c.start, c.end = start, end
        out.append(c)
    out.sort(key=lambda c: c.start)
    return out


def pick_clips(transcript: Transcript, cfg: Config) -> list[Clip]:
    backend = cfg.highlight_backend
    clips: list[Clip] = []
    if backend == "claude":
        try:
            clips = _pick_with_claude(transcript, cfg)
        except Exception as e:  # noqa: BLE001 — surface, then optionally fall back
            print(f"  ! Claude highlight detection failed: {e}")
            if cfg.allow_heuristic_fallback:
                print("  -> falling back to heuristic selection.")
                clips = _pick_heuristic(transcript, cfg)
            else:
                raise
    else:
        clips = _pick_heuristic(transcript, cfg)

    return _finalize(clips, transcript, cfg)
