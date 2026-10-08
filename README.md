# AI Podcast Clip Generator

Turn a long YouTube podcast (or a local video) into a set of vertical **9:16** short-form
clips for YouTube Shorts / TikTok / Reels — each with word-synced "karaoke" captions and a
suggestions file of titles, hooks, and hashtags.

**Phases 1 & 2 are complete.** The pipeline: download → transcribe → Claude picks highlights →
cut + center-crop to vertical → burn in word-synced captions → overlay a tone-driven reaction
character → export. (Phase 3 adds face-tracking crop + a web UI.)

## Pipeline

1. **Input** — a YouTube URL (via `yt-dlp`) or a local video file.
2. **Transcribe** — `faster-whisper` locally, with word-level timestamps.
3. **Highlights** — Claude reads the timestamped transcript and returns N self-contained
   clips with start/end, a title, a spoken hook, a short on-screen hook, a tone label, and
   hashtags (structured JSON output).
4. **Reframe** — `ffmpeg` cuts each segment and center-crops it to 9:16.
5. **Captions** — word-synced karaoke captions. Uses libass when available, otherwise a
   built-in Pillow renderer (so it works even on a minimal ffmpeg build).
6. **Overlays** — an original mascot in a corner (expression chosen from the tone) plus a
   persistent hook banner across the top.
7. **Output** — `output/NN_title.mp4` plus `output/SUGGESTIONS.md`.

## Setup

### 1. System dependencies
- **ffmpeg** (and ffprobe): `brew install ffmpeg`
- Python 3.10+ recommended (built/tested with 3.13).

### 2. Python environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Claude API key (for highlight detection)
Copy `.env.example` to `.env` and add your key:
```bash
cp .env.example .env
# then edit .env:  ANTHROPIC_API_KEY=sk-ant-...
```
No key handy? Run with `--no-claude` to use the built-in heuristic picker instead.

### Hardware note
`faster-whisper` runs locally on CPU (fast on Apple Silicon, no GPU/CUDA required here).
Transcription time scales with episode length and model size — for a first run, test on a
short clip or use `--max-source-minutes 15` and `--whisper-model base`.

## Usage

```bash
# Basic: 6 clips from a YouTube episode
python -m podcast_clipper "https://www.youtube.com/watch?v=..."

# Local file, 8 clips, 30–45s each
python -m podcast_clipper /path/to/episode.mp4 --num-clips 8 --min-seconds 30 --max-seconds 45

# Quick test: first 15 minutes only, small whisper model, no API key needed
python -m podcast_clipper "<url>" --max-source-minutes 15 --whisper-model base --no-claude
```

### Common flags
| Flag | Meaning |
|---|---|
| `--num-clips N` | How many clips to produce |
| `--min-seconds` / `--max-seconds` | Clip length window |
| `--whisper-model` | `tiny`/`base`/`small`/`medium`/`large-v3` (bigger = better + slower) |
| `--max-source-minutes N` | Only process the first N minutes (fast iteration) |
| `--no-claude` | Use heuristic highlight selection (no API key) |
| `--claude-model` | Override the Claude model (default `claude-opus-4-8`) |
| `--no-captions` | Skip burned-in captions |
| `--no-character` | Skip the reaction character overlay |
| `--character-set NAME` | Character asset folder under `assets/characters/` |
| `--no-hook` | Skip the on-screen hook banner |
| `--config path` | Use a different config file |

All defaults live in [`config.yaml`](config.yaml) and can be edited there instead of via flags.

## Web UI

Prefer a browser to the terminal:
```bash
python -m podcast_clipper.web      # then open http://127.0.0.1:5001
```
Paste a link, adjust options (clip count, length, Whisper model, captions/character toggles),
and watch live progress. Finished clips preview inline with download links. Each run is
isolated under `web_runs/<job-id>/`.

## Output
- `output/01_some-title.mp4`, `output/02_...mp4`, …
- `output/SUGGESTIONS.md` — title, hook, tone, hashtags, and timestamp per clip.

## Reaction character
The mascot lives in `assets/characters/<set>/` as one PNG per expression (neutral, laughing,
shocked, thinking, nodding). The built-in `bean` set is generated on first run.

**Use your own art:** drop transparent PNGs into `assets/characters/<your-name>/` and select
it with `--character-set <your-name>` (or `character_set:` in `config.yaml`). You can start
with just a single `neutral.png` — any missing expressions fall back to it, so you don't have
to draw all five up front. Any resolution works (scaled to `character_height_frac` of the
frame height, aspect preserved; portrait/square looks best). Position via `character_corner`.

Tone→expression: funny→laughing, shocking/intense→shocked, thoughtful→thinking,
heartwarming→nodding, otherwise neutral.

## Hook banner
Claude writes a short punchy `overlay_hook` per clip (≤~6 words), rendered as a persistent
banner across the top to boost watch time — separate from the captions (bottom) and character
(corner). Toggle with `--no-hook`; restyle via the `hook_*` keys in `config.yaml` (font, size,
top margin, colours, bar opacity).

## Cost
Transcription is free (local). The highlight step makes **one** Claude API call per run; cost
scales with transcript length (a ~2-hour episode is roughly a few tens of thousands of input
tokens). Use `--no-claude` to avoid API cost while iterating on the video pipeline.

## Roadmap
- **Phase 1 (done)** — CLI: URL → vertical clips with word-synced captions.
- **Phase 2 (done)** — tone-driven reaction-character overlay (original "Bean" mascot; swappable).
- **Phase 3 (in progress)** — web UI done (`python -m podcast_clipper.web`); face-tracking crop next.
