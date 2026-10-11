"""Resolve the input: download a YouTube URL with yt-dlp, or accept a local file."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_CACHE_NAME = "sources.json"  # url -> downloaded file, so repeat runs skip yt-dlp


@dataclass
class Source:
    video_path: Path
    title: str
    duration: float  # seconds (0 if unknown)
    url: str = ""
    video_id: str = ""
    cached: bool = False  # True when reused from the work-dir cache


def _looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://") or s.startswith("www.")


def resolve_source(input_str: str, work_dir: Path, max_height: int = 1080) -> Source:
    """Return a local video file for either a URL or an existing path."""
    if not _looks_like_url(input_str):
        p = Path(input_str).expanduser()
        if not p.exists():
            raise FileNotFoundError(
                f"Input is neither a URL nor an existing file: {input_str}"
            )
        from .util import ffprobe_duration
        try:
            dur = ffprobe_duration(p)
        except Exception:  # noqa: BLE001
            dur = 0.0
        return Source(video_path=p, title=p.stem, duration=dur, url=str(p))
    return _download(input_str, work_dir, max_height)


def _read_cache(work_dir: Path) -> dict:
    p = work_dir / _CACHE_NAME
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _download(url: str, work_dir: Path, max_height: int = 1080) -> Source:
    hit = _read_cache(work_dir).get(url)
    if hit and Path(hit["video_path"]).exists():
        return Source(video_path=Path(hit["video_path"]), title=hit.get("title", ""),
                      duration=float(hit.get("duration") or 0.0), url=url,
                      video_id=hit.get("video_id", ""), cached=True)
    import yt_dlp

    work_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(work_dir / "%(id)s.%(ext)s")
    h = max_height
    ydl_opts = {
        # Best video+audio up to max_height, merged to mp4. Falls back gracefully.
        "format": (
            f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
        ),
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # Resolve the actual output path yt-dlp wrote.
        path = Path(ydl.prepare_filename(info))
        if path.suffix != ".mp4":
            mp4 = path.with_suffix(".mp4")
            if mp4.exists():
                path = mp4
    if not path.exists():
        raise RuntimeError(f"yt-dlp finished but output not found: {path}")
    src = Source(
        video_path=path.resolve(),
        title=info.get("title") or path.stem,
        duration=float(info.get("duration") or 0.0),
        url=url,
        video_id=info.get("id") or "",
    )
    cache = _read_cache(work_dir)
    cache[url] = {"video_path": str(src.video_path), "title": src.title,
                  "duration": src.duration, "video_id": src.video_id}
    (work_dir / _CACHE_NAME).write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return src
