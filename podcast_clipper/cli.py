"""Command-line entry point."""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from .config import Config
from .util import check_tool, load_dotenv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="podcast_clipper",
        description="Turn a YouTube podcast (or local video) into vertical short-form clips "
                    "with word-synced captions.",
    )
    p.add_argument("input", help="YouTube URL or path to a local video file")
    p.add_argument("--config", help="Path to config.yaml (default: ./config.yaml)")

    p.add_argument("--num-clips", type=int, dest="num_clips")
    p.add_argument("--min-seconds", type=float, dest="min_clip_seconds")
    p.add_argument("--max-seconds", type=float, dest="max_clip_seconds")
    p.add_argument("--output-dir", dest="output_dir")
    p.add_argument("--work-dir", dest="work_dir")

    p.add_argument("--whisper-model", dest="whisper_model",
                   help="tiny | base | small | medium | large-v3")
    p.add_argument("--max-source-minutes", type=float, dest="max_source_minutes",
                   help="Only process the first N minutes (quick test runs)")

    p.add_argument("--highlight-backend", dest="highlight_backend", choices=["claude", "heuristic"])
    p.add_argument("--claude-model", dest="claude_model")
    p.add_argument("--no-claude", action="store_true",
                   help="Shortcut for --highlight-backend heuristic (no API key needed)")

    p.add_argument("--no-captions", action="store_true", help="Disable burned-in captions")
    p.add_argument("--no-character", action="store_true", help="Disable the reaction character overlay")
    p.add_argument("--character-set", dest="character_set", help="Character asset folder under assets/characters/")
    p.add_argument("--no-hook", action="store_true", help="Disable the on-screen hook banner")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--transcript-only", action="store_true",
                      help="Download + transcribe only; write transcript.json and transcript.txt "
                           "to --output-dir (no clips). Cached in --work-dir for a later --clips run.")
    mode.add_argument("--clips", metavar="PATH.json",
                      help="Skip clip selection and cut exactly the clips in this JSON file "
                           "(list of {start, end, title, hook?, caption?, hashtags?, reason?, tone?}).")
    return p


def _write_error(out_dir: str | None, message: str) -> None:
    """Leave an ERROR.txt next to the outputs so callers can see what went wrong."""
    try:
        d = Path(out_dir or "output")
        d.mkdir(parents=True, exist_ok=True)
        (d / "ERROR.txt").write_text(message.rstrip() + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # pull ANTHROPIC_API_KEY from .env if present
    args = build_parser().parse_args(argv)

    if not check_tool("ffmpeg") or not check_tool("ffprobe"):
        msg = "ERROR: ffmpeg/ffprobe not found on PATH. Install with: brew install ffmpeg"
        print(msg, file=sys.stderr)
        _write_error(args.output_dir, msg)
        return 2

    skip = ("input", "config", "no_claude", "no_captions", "no_character", "no_hook",
            "transcript_only", "clips")
    overrides = {k: v for k, v in vars(args).items() if k not in skip and v is not None}
    if args.no_claude:
        overrides["highlight_backend"] = "heuristic"
    if args.no_captions:
        overrides["captions_enabled"] = False
    if args.no_character:
        overrides["character_enabled"] = False
    if args.no_hook:
        overrides["hook_enabled"] = False

    cfg = Config.load(args.config, overrides)
    stale = Path(cfg.output_dir) / "ERROR.txt"
    if stale.exists():
        stale.unlink()  # don't leave an old failure next to fresh output

    if args.clips and not Path(args.clips).is_file():
        msg = f"ERROR: clips file not found: {args.clips}"
        print(msg, file=sys.stderr)
        _write_error(cfg.output_dir, msg)
        return 2

    # Friendly preflight for the common gotcha (only the built-in selector uses Claude).
    if cfg.highlight_backend == "claude" and not (args.transcript_only or args.clips):
        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("NOTE: ANTHROPIC_API_KEY not set. Either add it to a .env file, "
                  "or run with --no-claude for heuristic selection.", file=sys.stderr)

    from .pipeline import run, run_transcript_only, run_with_clips
    try:
        if args.transcript_only:
            run_transcript_only(args.input, cfg)
        elif args.clips:
            run_with_clips(args.input, args.clips, cfg)
        else:
            run(args.input, cfg)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        _write_error(cfg.output_dir, "ERROR: interrupted")
        return 130
    except Exception as e:  # noqa: BLE001
        msg = str(e) if str(e).startswith("ERROR") else f"ERROR: {e}"
        print(f"\n{msg}", file=sys.stderr)
        _write_error(cfg.output_dir, f"{msg}\n\ninput: {args.input}\n\n{traceback.format_exc()}")
        return 1
    return 0
