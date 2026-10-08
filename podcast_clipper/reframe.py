"""Cut a clip, reframe to vertical 9:16 (center-crop), and burn in captions."""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .util import run


def vertical_filter(cfg: Config, ass_basename: str | None) -> str:
    """Build the -vf filter chain.

    scale(...increase) + crop center-crops to 9:16 for any input aspect ratio.
    Then optionally burn the .ass captions (referenced by basename; ffmpeg runs
    with cwd set to the work dir so we avoid filtergraph path-escaping issues).
    """
    chain = (
        f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=increase,"
        f"crop={cfg.width}:{cfg.height},setsar=1"
    )
    if ass_basename:
        chain += f",ass={ass_basename}"
    return chain


def _char_xy(corner: str, margin: int) -> tuple[str, str]:
    """ffmpeg overlay x:y expressions for a corner (W/H=main, w/h=overlay)."""
    corner = (corner or "bottom-right").lower()
    x = f"W-w-{margin}" if "right" in corner else f"{margin}"
    y = f"{margin}" if "top" in corner else f"H-h-{margin}"
    return x, y


def render_clip(
    *,
    source: Path,
    start: float,
    duration: float,
    cfg: Config,
    work_dir: Path,
    out_path: Path,
    ass_basename: str | None = None,
    overlay_path: Path | None = None,
    char_path: Path | None = None,
    hook_path: Path | None = None,
) -> Path:
    """Cut + reframe a clip to vertical, then layer (in order) libass or Pillow
    captions and the reaction character. ffmpeg runs with cwd=work_dir so the
    `ass=` filter can use a basename; all other paths are absolute."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    source = Path(source).resolve()
    out_abs = str(out_path.resolve())
    tail = [
        "-r", str(cfg.fps),
        "-c:v", "libx264", "-preset", cfg.video_preset, "-crf", str(cfg.video_crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", cfg.audio_bitrate,
        "-movflags", "+faststart",
        out_abs,
    ]

    # Fast path: nothing to composite.
    if ass_basename is None and overlay_path is None and char_path is None and hook_path is None:
        cmd = [
            "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source),
            "-t", f"{duration:.3f}", "-vf", vertical_filter(cfg, None), *tail,
        ]
        run(cmd, cwd=work_dir)
        return out_path

    inputs = ["-ss", f"{start:.3f}", "-i", str(source)]
    base = (
        f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=increase,"
        f"crop={cfg.width}:{cfg.height},setsar=1"
    )
    if ass_basename:
        base += f",ass={ass_basename}"
    parts = [f"[0:v]{base}[b0]"]
    last, idx = "b0", 1

    if overlay_path is not None:  # caption overlay video (Pillow path)
        inputs += ["-i", str(Path(overlay_path).resolve())]
        parts.append(f"[{last}][{idx}:v]overlay=0:0:eof_action=pass[b{idx}]")
        last, idx = f"b{idx}", idx + 1

    if char_path is not None:  # reaction character image, scaled + corner-placed
        inputs += ["-loop", "1", "-i", str(Path(char_path).resolve())]
        ch = max(1, int(cfg.height * cfg.character_height_frac))
        x, y = _char_xy(cfg.character_corner, cfg.character_margin)
        parts.append(f"[{idx}:v]scale=-1:{ch}[ch]")
        parts.append(f"[{last}][ch]overlay={x}:{y}:eof_action=pass[b{idx}]")
        last, idx = f"b{idx}", idx + 1

    if hook_path is not None:  # full-frame hook banner, composited on top
        inputs += ["-loop", "1", "-i", str(Path(hook_path).resolve())]
        parts.append(f"[{last}][{idx}:v]overlay=0:0:eof_action=pass[b{idx}]")
        last, idx = f"b{idx}", idx + 1

    parts.append(f"[{last}]format=yuv420p[v]")
    cmd = [
        "ffmpeg", "-y", *inputs, "-t", f"{duration:.3f}",
        "-filter_complex", ";".join(parts),
        "-map", "[v]", "-map", "0:a?", *tail,
    ]
    run(cmd, cwd=work_dir)
    return out_path
