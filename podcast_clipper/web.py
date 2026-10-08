"""Lightweight web UI: paste a link -> watch progress -> download clips.

Run:  python -m podcast_clipper.web   (then open http://127.0.0.1:5001)
Wraps the same pipeline as the CLI; each job runs in a background thread and
reports progress, which the page polls.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from .config import Config
from .pipeline import PipelineResult, run as run_pipeline
from .util import fmt_timestamp, load_dotenv

app = Flask(__name__)
RUNS_DIR = Path("web_runs")


@dataclass
class Job:
    id: str
    status: str = "queued"  # queued | running | done | error
    log: list[str] = field(default_factory=list)
    error: str | None = None
    result: PipelineResult | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


JOBS: dict[str, Job] = {}


def _job_dir(job_id: str) -> Path:
    return RUNS_DIR / job_id / "clips"


def _run_job(job: Job, url: str, overrides: dict) -> None:
    job.status = "running"
    base = RUNS_DIR / job.id
    overrides["output_dir"] = str(base / "clips")
    overrides["work_dir"] = str(base / "work")
    try:
        cfg = Config.load(overrides=overrides)
        job.result = run_pipeline(url, cfg, progress=lambda m: job.log.append(m))
        job.status = "done"
    except Exception as e:  # noqa: BLE001 — surface to the UI
        job.error = str(e)
        job.log.append(f"ERROR: {e}")
        job.status = "error"


@app.post("/api/jobs")
def create_job():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "A YouTube URL (or local path) is required."}), 400

    overrides: dict = {}
    # Numeric / string options, all optional.
    for key, cast in (("num_clips", int), ("min_clip_seconds", float),
                      ("max_clip_seconds", float), ("whisper_model", str),
                      ("max_source_minutes", float)):
        if data.get(key) not in (None, ""):
            try:
                overrides[key] = cast(data[key])
            except (TypeError, ValueError):
                pass
    overrides["highlight_backend"] = "claude" if data.get("use_claude", True) else "heuristic"
    overrides["captions_enabled"] = bool(data.get("captions", True))
    overrides["character_enabled"] = bool(data.get("character", True))
    overrides["hook_enabled"] = bool(data.get("hook", True))
    if data.get("character_set"):
        overrides["character_set"] = str(data["character_set"]).strip()

    job = Job(id=uuid.uuid4().hex[:12])
    JOBS[job.id] = job
    threading.Thread(target=_run_job, args=(job, url, overrides), daemon=True).start()
    return jsonify({"id": job.id})


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        abort(404)
    payload: dict = {"id": job.id, "status": job.status, "log": list(job.log), "error": job.error}
    if job.status == "done" and job.result:
        r = job.result
        payload["title"] = r.title
        payload["seconds"] = round(r.seconds)
        payload["suggestions"] = r.suggestions.read_text(encoding="utf-8")
        payload["clips"] = [
            {
                "file": f.name,
                "url": f"/clips/{job.id}/{f.name}",
                "title": c.title,
                "tone": c.tone,
                "hook": c.hook,
                "overlay_hook": c.overlay_hook,
                "hashtags": c.hashtags,
                "range": f"{fmt_timestamp(c.start)}–{fmt_timestamp(c.end)}",
                "duration": round(c.duration),
            }
            for c, f in zip(r.clips, r.out_files)
        ]
    return jsonify(payload)


@app.get("/clips/<job_id>/<path:filename>")
def download_clip(job_id: str, filename: str):
    if job_id not in JOBS:
        abort(404)
    return send_from_directory(_job_dir(job_id).resolve(), filename, as_attachment=False)


@app.get("/")
def index():
    return INDEX_HTML


INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Podcast Clip Generator</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 960px; margin: 0 auto;
         padding: 24px; line-height: 1.5; }
  h1 { font-size: 22px; font-weight: 600; margin: 0 0 4px; }
  .sub { color: #888; margin: 0 0 20px; }
  form { display: grid; gap: 12px; padding: 16px; border: 1px solid #8884; border-radius: 12px; }
  .row { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; }
  label { font-size: 14px; display: flex; gap: 6px; align-items: center; }
  input[type=text], input[type=number], select { padding: 8px; border: 1px solid #8886;
         border-radius: 8px; background: transparent; color: inherit; font-size: 14px; }
  input[type=text] { width: 100%; }
  button { padding: 10px 18px; border: 0; border-radius: 8px; background: #4C86F2; color: #fff;
           font-size: 15px; font-weight: 500; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  #progress { white-space: pre-wrap; font-family: ui-monospace, monospace; font-size: 13px;
              background: #8881; border-radius: 8px; padding: 12px; margin-top: 16px; display: none; }
  .clips { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px;
           margin-top: 20px; }
  .card { border: 1px solid #8884; border-radius: 12px; padding: 12px; }
  .card video { width: 100%; border-radius: 8px; background: #000; }
  .card h3 { font-size: 15px; margin: 8px 0 4px; }
  .meta { font-size: 12px; color: #888; }
  .tone { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 99px;
          background: #4C86F233; color: #4C86F2; margin-left: 6px; }
  .tags { font-size: 12px; color: #4C86F2; margin-top: 6px; }
  .dl { display: inline-block; margin-top: 8px; font-size: 13px; }
</style></head>
<body>
  <h1>AI Podcast Clip Generator</h1>
  <p class="sub">Paste a YouTube podcast link and get vertical clips with captions and a reaction character.</p>
  <form id="f">
    <input type="text" id="url" placeholder="https://youtu.be/..." required>
    <div class="row">
      <label>Clips <input type="number" id="num_clips" value="6" min="1" max="20" style="width:64px"></label>
      <label>Min s <input type="number" id="min_clip_seconds" value="20" style="width:64px"></label>
      <label>Max s <input type="number" id="max_clip_seconds" value="60" style="width:64px"></label>
      <label>Whisper
        <select id="whisper_model">
          <option value="base" selected>base (fast)</option>
          <option value="small">small</option>
          <option value="medium">medium (slow)</option>
        </select>
      </label>
      <label>First N min <input type="number" id="max_source_minutes" placeholder="all" style="width:64px"></label>
    </div>
    <div class="row">
      <label><input type="checkbox" id="use_claude" checked> Use Claude</label>
      <label><input type="checkbox" id="captions" checked> Captions</label>
      <label><input type="checkbox" id="character" checked> Character</label>
      <label><input type="checkbox" id="hook" checked> Hook banner</label>
      <label>Set <input type="text" id="character_set" placeholder="bean" style="width:80px"></label>
      <button type="submit" id="go">Generate clips</button>
    </div>
  </form>
  <div id="progress"></div>
  <h2 id="resultTitle" style="display:none"></h2>
  <div class="clips" id="clips"></div>

<script>
const f = document.getElementById('f');
const prog = document.getElementById('progress');
const clipsEl = document.getElementById('clips');
const titleEl = document.getElementById('resultTitle');
const go = document.getElementById('go');

f.addEventListener('submit', async (e) => {
  e.preventDefault();
  clipsEl.innerHTML = ''; titleEl.style.display = 'none';
  prog.style.display = 'block'; prog.textContent = 'Starting...';
  go.disabled = true;
  const body = {
    url: document.getElementById('url').value,
    num_clips: document.getElementById('num_clips').value,
    min_clip_seconds: document.getElementById('min_clip_seconds').value,
    max_clip_seconds: document.getElementById('max_clip_seconds').value,
    whisper_model: document.getElementById('whisper_model').value,
    max_source_minutes: document.getElementById('max_source_minutes').value,
    use_claude: document.getElementById('use_claude').checked,
    captions: document.getElementById('captions').checked,
    character: document.getElementById('character').checked,
    hook: document.getElementById('hook').checked,
    character_set: document.getElementById('character_set').value,
  };
  const res = await fetch('/api/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)});
  const data = await res.json();
  if (data.error) { prog.textContent = data.error; go.disabled = false; return; }
  poll(data.id);
});

async function poll(id) {
  const res = await fetch('/api/jobs/' + id);
  const j = await res.json();
  prog.textContent = (j.log || []).join('\\n');
  if (j.status === 'done') { go.disabled = false; render(j); return; }
  if (j.status === 'error') { go.disabled = false; return; }
  setTimeout(() => poll(id), 1500);
}

function render(j) {
  titleEl.textContent = j.title + '  ·  ' + j.seconds + 's';
  titleEl.style.display = 'block';
  clipsEl.innerHTML = '';
  for (const c of j.clips) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML =
      '<video controls preload="metadata" src="' + c.url + '"></video>' +
      '<h3>' + c.title + '<span class="tone">' + c.tone + '</span></h3>' +
      '<div class="meta">' + c.range + ' · ' + c.duration + 's · hook: ' + (c.overlay_hook || '') + '</div>' +
      '<div class="meta">' + c.hook + '</div>' +
      '<div class="tags">' + (c.hashtags || []).join(' ') + '</div>' +
      '<a class="dl" href="' + c.url + '" download>Download</a>';
    clipsEl.appendChild(card);
  }
}
</script>
</body></html>
"""


def main() -> None:
    load_dotenv()
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    print("Podcast Clipper web UI -> http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, threaded=True)


if __name__ == "__main__":
    main()
