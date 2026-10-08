"""Configuration: defaults <- config.yaml <- CLI overrides."""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "num_clips": 6,
    "min_clip_seconds": 20,
    "max_clip_seconds": 60,
    "output_dir": "output",
    "work_dir": "work",
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "video_crf": 20,
    "video_preset": "veryfast",
    "audio_bitrate": "160k",
    "max_download_height": 1080,  # cap yt-dlp video height (don't fetch 4K to make a 1080 vertical)
    "whisper_model": "small",
    "whisper_compute_type": "int8",
    "whisper_device": "auto",
    "whisper_language": None,
    "max_source_minutes": None,
    "highlight_backend": "claude",
    "claude_model": "claude-opus-4-8",
    "claude_max_tokens": 8000,
    "allow_heuristic_fallback": True,
    "captions_enabled": True,
    "caption_font": "Arial",
    "caption_fontsize": 84,
    "caption_words_per_line": 4,
    "caption_primary_color": "&H0000FFFF",
    "caption_secondary_color": "&H00FFFFFF",
    "caption_outline_color": "&H00000000",
    "caption_outline": 4,
    "caption_margin_v": 600,
    "character_enabled": True,
    "character_set": "bean",          # asset folder under assets/characters/
    "character_corner": "bottom-right",  # bottom-right|bottom-left|top-right|top-left
    "character_height_frac": 0.22,    # character height as a fraction of video height
    "character_margin": 40,           # px from the frame edges
    "hook_enabled": True,             # persistent on-screen hook banner (top)
    "hook_font": "Arial",
    "hook_fontsize": 62,
    "hook_margin_top": 96,            # px from the top edge
    "hook_max_width_frac": 0.86,      # banner max width as a fraction of video width
    "hook_text_color": "&H00FFFFFF",  # white (ASS &HAABBGGRR)
    "hook_bg_color": "&H00000000",    # black bar behind the text
    "hook_bg_opacity": 0.55,          # 0 = transparent, 1 = opaque
}


@dataclass
class Config:
    num_clips: int
    min_clip_seconds: float
    max_clip_seconds: float
    output_dir: str
    work_dir: str
    width: int
    height: int
    fps: int
    video_crf: int
    video_preset: str
    audio_bitrate: str
    max_download_height: int
    whisper_model: str
    whisper_compute_type: str
    whisper_device: str
    whisper_language: str | None
    max_source_minutes: float | None
    highlight_backend: str
    claude_model: str
    claude_max_tokens: int
    allow_heuristic_fallback: bool
    captions_enabled: bool
    caption_font: str
    caption_fontsize: int
    caption_words_per_line: int
    caption_primary_color: str
    caption_secondary_color: str
    caption_outline_color: str
    caption_outline: int
    caption_margin_v: int
    character_enabled: bool
    character_set: str
    character_corner: str
    character_height_frac: float
    character_margin: int
    hook_enabled: bool
    hook_font: str
    hook_fontsize: int
    hook_margin_top: int
    hook_max_width_frac: float
    hook_text_color: str
    hook_bg_color: str
    hook_bg_opacity: float

    @classmethod
    def load(cls, config_path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> "Config":
        data = dict(DEFAULTS)
        path = Path(config_path) if config_path else Path("config.yaml")
        if path.exists():
            loaded = yaml.safe_load(path.read_text()) or {}
            data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
        if overrides:
            data.update({k: v for k, v in overrides.items() if v is not None and k in DEFAULTS})
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
