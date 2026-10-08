"""End-to-end pipeline: input -> transcript -> highlights -> vertical clips + captions."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .captions import build_ass
from .captions_pil import render_hook_image, render_overlay_video
from .character import expression_for_tone, resolve_assets
from .config import Config
from .download import resolve_source
from .highlights import Clip, pick_clips
from .reframe import render_clip
from .transcribe import transcribe
from .util import ffmpeg_has_libass, fmt_timestamp, slugify


def _write_suggestions(out_dir: Path, title: str, clips: list[Clip], files: list[Path]) -> Path:
    path = out_dir / "SUGGESTIONS.md"
    lines = [f"# Clip suggestions — {title}", ""]
    for i, (c, f) in enumerate(zip(clips, files), 1):
        lines += [
            f"## {i}. {c.title}",
            f"- **File:** `{f.name}`",
            f"- **Timestamp:** {fmt_timestamp(c.start)}–{fmt_timestamp(c.end)} ({c.duration:.0f}s)",
            f"- **Tone:** {c.tone}",
            f"- **On-screen hook:** {c.overlay_hook}",
            f"- **Spoken hook:** {c.hook}",
            f"- **Hashtags:** {' '.join(c.hashtags)}",
            f"- **Why:** {c.reason}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@dataclass
class PipelineResult:
    title: str
    out_files: list[Path]
    clips: list[Clip]
    suggestions: Path
    seconds: float


def run(input_str: str, cfg: Config,
        progress: Optional[Callable[[str], None]] = None) -> PipelineResult:
    """Run the full pipeline. `progress` receives each status line (defaults to print)."""
    emit = progress if progress is not None else print
    t0 = time.time()
    work_dir = Path(cfg.work_dir)
    out_dir = Path(cfg.output_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    emit("[1/5] Resolving input...")
    source = resolve_source(input_str, work_dir, cfg.max_download_height)
    emit(f"      {source.title}")

    emit(f"[2/5] Transcribing (faster-whisper '{cfg.whisper_model}')... this can take a while")
    transcript = transcribe(
        source.video_path, work_dir,
        model=cfg.whisper_model, compute_type=cfg.whisper_compute_type,
        device=cfg.whisper_device, language=cfg.whisper_language,
        max_source_minutes=cfg.max_source_minutes,
    )
    emit(f"      {len(transcript.segments)} segments, {transcript.duration/60:.1f} min, lang={transcript.language}")
    if not transcript.segments:
        raise RuntimeError("Transcription produced no segments — is there audio in the source?")

    emit(f"[3/5] Selecting {cfg.num_clips} clips ({cfg.highlight_backend})...")
    clips = pick_clips(transcript, cfg)
    emit(f"      got {len(clips)} clips")
    if not clips:
        raise RuntimeError("No clips selected.")

    use_captions = cfg.captions_enabled
    use_libass = use_captions and ffmpeg_has_libass()
    char_assets: dict[str, Path] = {}
    if cfg.character_enabled:
        char_assets = resolve_assets(Path("assets/characters"), cfg.character_set)
        if not char_assets:
            emit(f"      (character '{cfg.character_set}' has no PNGs in assets/characters/ — skipping)")

    layers = []
    if use_captions:
        layers.append("captions (libass)" if use_libass else "captions (Pillow overlay)")
    if char_assets:
        layers.append(f"{cfg.character_set} character")
    if cfg.hook_enabled:
        layers.append("hook banner")
    emit(f"[4/5] Rendering vertical clips" + (f" + {' + '.join(layers)}" if layers else "") + "...")

    out_files: list[Path] = []
    for i, c in enumerate(clips, 1):
        ass_basename: str | None = None
        overlay_path = None
        if use_captions:
            words = transcript.words_in_range(c.start, c.end)
            if words:
                if use_libass:
                    ass_basename = f"clip_{i:02d}.ass"
                    build_ass(words, c.start, cfg, work_dir / ass_basename)
                else:
                    overlay_path = render_overlay_video(
                        words, c.start, c.duration, cfg, work_dir / f"clip_{i:02d}_cap.mov")
        char_path = char_assets.get(expression_for_tone(c.tone)) if char_assets else None
        hook_path = None
        if cfg.hook_enabled and c.overlay_hook:
            hook_path = render_hook_image(c.overlay_hook, cfg, work_dir / f"clip_{i:02d}_hook.png")
        out_name = f"{i:02d}_{slugify(c.title)}.mp4"
        out_path = out_dir / out_name
        expr = expression_for_tone(c.tone) if char_assets else "-"
        emit(f"      [{i}/{len(clips)}] {fmt_timestamp(c.start)}–{fmt_timestamp(c.end)}  "
             f"{c.title}  [{c.tone}→{expr}]  hook: {c.overlay_hook!r}")
        render_clip(
            source=source.video_path, start=c.start, duration=c.duration,
            cfg=cfg, work_dir=work_dir, ass_basename=ass_basename,
            overlay_path=overlay_path, char_path=char_path, hook_path=hook_path,
            out_path=out_path,
        )
        out_files.append(out_path)

    emit("[5/5] Writing suggestions...")
    sug = _write_suggestions(out_dir, source.title, clips, out_files)
    secs = time.time() - t0
    emit(f"Done in {secs:.0f}s — {len(out_files)} clips ready.")
    return PipelineResult(title=source.title, out_files=out_files, clips=clips,
                          suggestions=sug, seconds=secs)
