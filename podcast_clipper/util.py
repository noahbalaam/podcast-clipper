"""Small shared helpers: env loading, subprocess wrappers, slugs, ffprobe."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (no overwrite).

    Avoids a python-dotenv dependency. Existing env vars win.
    """
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def run(cmd: list[str], cwd: str | Path | None = None, quiet: bool = True) -> subprocess.CompletedProcess:
    """Run a command, raising a readable error if it fails."""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-25:]
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd[:3])} ...\n" + "\n".join(tail)
        )
    return proc


def ffprobe_duration(path: str | Path) -> float:
    """Return media duration in seconds."""
    proc = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ])
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def slugify(text: str, max_len: int = 50) -> str:
    """Filesystem-safe slug from a title."""
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len].strip("-") or "clip"


def fmt_timestamp(seconds: float) -> str:
    """Seconds -> M:SS (or H:MM:SS) for human-readable display."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def check_tool(name: str) -> bool:
    """True if a CLI tool is on PATH."""
    from shutil import which
    return which(name) is not None


_LIBASS: bool | None = None


def ffmpeg_has_libass() -> bool:
    """True if this ffmpeg build exposes the `ass`/`subtitles` filter (libass).

    Some builds (e.g. minimal Homebrew bottles) ship without it; in that case we
    fall back to the Pillow-based caption renderer. Result is cached.
    """
    global _LIBASS
    if _LIBASS is None:
        try:
            proc = subprocess.run(
                ["ffmpeg", "-hide_banner", "-filters"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            out = proc.stdout
            _LIBASS = (" ass " in out) or (" subtitles " in out)
        except Exception:  # noqa: BLE001
            _LIBASS = False
    return _LIBASS
