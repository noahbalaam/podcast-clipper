"""Transcription with faster-whisper, producing word-level timestamps."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .util import run


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    segments: list[Segment]
    language: str
    duration: float

    def all_words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]

    def words_in_range(self, start: float, end: float) -> list[Word]:
        return [w for w in self.all_words() if w.start >= start - 0.05 and w.end <= end + 0.05]

    def transcript_for_prompt(self) -> str:
        """Compact, timestamped transcript for the highlight model.

        One line per segment: [start-end] text   (times in seconds)
        """
        lines = []
        for s in self.segments:
            lines.append(f"[{s.start:.1f}-{s.end:.1f}] {s.text.strip()}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        segs = [
            Segment(start=float(s["start"]), end=float(s["end"]), text=s["text"],
                    words=[Word(float(w["start"]), float(w["end"]), w["text"])
                           for w in s.get("words", [])])
            for s in d.get("segments", [])
        ]
        return cls(segments=segs, language=d.get("language") or "",
                   duration=float(d.get("duration") or 0.0))


def _cache_path(video_path: Path, work_dir: Path, model: str, language: str | None,
                max_source_minutes: float | None) -> Path:
    mins = f"{max_source_minutes:g}m" if max_source_minutes else "full"
    return work_dir / f"{video_path.stem}.transcript.{model}.{language or 'auto'}.{mins}.json"


def find_cached_transcript(video_path: Path, work_dir: Path) -> Path | None:
    """Most recent cached transcript for this video, whatever settings made it."""
    hits = sorted(work_dir.glob(f"{video_path.stem}.transcript.*.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def load_transcript(path: Path) -> Transcript:
    return Transcript.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _extract_audio(video_path: Path, work_dir: Path) -> Path:
    """Extract mono 16 kHz WAV — the format Whisper expects."""
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / (video_path.stem + ".16k.wav")
    run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(audio_path),
    ])
    return audio_path


def transcribe(video_path: Path, work_dir: Path, *, model: str, compute_type: str,
               device: str, language: str | None, max_source_minutes: float | None) -> Transcript:
    cache = _cache_path(video_path, work_dir, model, language, max_source_minutes)
    if cache.exists():
        try:
            return load_transcript(cache)
        except Exception:  # noqa: BLE001 — corrupt cache, just redo it
            pass

    from faster_whisper import WhisperModel

    audio_path = _extract_audio(video_path, work_dir)
    whisper = WhisperModel(model, device=device, compute_type=compute_type)

    clip_end = max_source_minutes * 60 if max_source_minutes else None
    segments_iter, info = whisper.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
        language=language,
    )

    segments: list[Segment] = []
    for seg in segments_iter:
        if clip_end is not None and seg.start > clip_end:
            break
        words = []
        for w in (seg.words or []):
            if w.start is None or w.end is None:
                continue
            words.append(Word(start=float(w.start), end=float(w.end), text=w.word))
        segments.append(Segment(start=float(seg.start), end=float(seg.end),
                                 text=seg.text, words=words))

    duration = segments[-1].end if segments else 0.0
    result = Transcript(segments=segments, language=info.language, duration=duration)
    if segments:
        work_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result.to_dict()), encoding="utf-8")
    return result
