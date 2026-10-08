"""Transcription with faster-whisper, producing word-level timestamps."""
from __future__ import annotations

from dataclasses import dataclass, field
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
    return Transcript(segments=segments, language=info.language, duration=duration)
