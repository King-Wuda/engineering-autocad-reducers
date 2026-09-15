"""Upload web UI.

A small FastAPI app: drop a PDF on the page, watch the tiles go by, read the
report. Scans run on a background thread and the browser polls for progress,
because a D-size sheet takes minutes and an HTTP request should not be held
open that long.

Binds to localhost by default - it accepts file uploads and spends API credits,
so it is a local tool, not something to expose.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .report import render_html, render_json, render_markdown
from .scan import ScanConfig, scan_pdf
from .vision import DEFAULT_MODEL, Scanner

log = logging.getLogger("pid_scan.server")

#: Refuse anything larger. A big multi-sheet P&ID set is ~40 MB; past this it
#: is almost certainly not a drawing.
MAX_UPLOAD_BYTES = 128 * 1024 * 1024


@dataclass
class Job:
    id: str
    filename: str
    state: str = "queued"          # queued | running | done | error
    log: List[str] = field(default_factory=list)
    error: str = ""
    html: str = ""
    markdown: str = ""
    json: str = ""
    stats: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def say(self, message: str) -> None:
        with self._lock:
            self.log.append(message)
            del self.log[:-200]   # keep the tail, this can get long

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "id": self.id, "filename": self.filename, "state": self.state,
                "log": list(self.log), "error": self.error, "stats": self.stats,
            }


class JobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def add(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)


def create_app(model: str = DEFAULT_MODEL) -> FastAPI:
    app = FastAPI(title="pid-scan", docs_url=None, redoc_url=None)
    store = JobStore()
    workdir = Path(tempfile.mkdtemp(prefix="pid-scan-"))

    def run_job(job: Job, pdf: Path, config: ScanConfig) -> None:
        job.state = "running"
        try:
            scanner = Scanner(model=model, concurrency=config.concurrency)
            images: Dict[int, bytes] = {}
            drawing = scan_pdf(pdf, scanner, config, progress=job.say, images=images)
            job.html = render_html(drawing, images)
            job.markdown = render_markdown(drawing)
            job.json = render_json(drawing)
            job.stats = drawing.stats
            job.state = "done"
            job.say("done")
        except Exception as exc:
            log.exception("scan failed")
            job.error = f"{type(exc).__name__}: {exc}"
            job.state = "error"
            job.say(f"failed: {job.error}")
        finally:
            pdf.unlink(missing_ok=True)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.post("/api/scan")
    async def start_scan(
        file: UploadFile = File(...),
        preset: str = Form("balanced"),
        pages: str = Form(""),
        synthesize: str = Form("yes"),
    ) -> JSONResponse:
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, "please upload a PDF")

        job = Job(id=uuid.uuid4().hex[:12], filename=file.filename or "drawing.pdf")
        target = workdir / f"{job.id}.pdf"

        size = 0
        with target.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    fh.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(413, "file is larger than 128 MB")
                fh.write(chunk)

        if target.read_bytes()[:5] != b"%PDF-":
            target.unlink(missing_ok=True)
            raise HTTPException(400, "that file is not a PDF")

        try:
            config = ScanConfig.preset(preset)
        except ValueError as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(400, str(exc))

        config.synthesize = synthesize == "yes"
        if pages.strip():
            from .cli import _parse_pages
            try:
                config.pages = _parse_pages(pages)
            except ValueError:
                raise HTTPException(400, "could not read the page range")

        store.add(job)
        threading.Thread(target=run_job, args=(job, target, config), daemon=True).start()
        return JSONResponse({"id": job.id})

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> JSONResponse:
        job = store.get(job_id)
        if not job:
            raise HTTPException(404, "no such job")
        return JSONResponse(job.snapshot())

    @app.get("/report/{job_id}", response_class=HTMLResponse)
    def report(job_id: str) -> str:
        job = store.get(job_id)
        if not job:
            raise HTTPException(404, "no such job")
        if job.state != "done":
            raise HTTPException(409, f"scan is {job.state}")
        return job.html

    @app.get("/api/jobs/{job_id}/markdown", response_class=PlainTextResponse)
    def markdown(job_id: str) -> str:
        job = store.get(job_id)
        if not job or job.state != "done":
            raise HTTPException(404, "not ready")
        return job.markdown

    @app.get("/api/jobs/{job_id}/json")
    def as_json(job_id: str) -> PlainTextResponse:
        job = store.get(job_id)
        if not job or job.state != "done":
            raise HTTPException(404, "not ready")
        return PlainTextResponse(job.json, media_type="application/json")

    @app.on_event("shutdown")
    def cleanup() -> None:
        shutil.rmtree(workdir, ignore_errors=True)

    return app


INDEX_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>pid-scan</title>
<style>
:root{color-scheme:light;--surface-0:#f6f6f4;--surface-1:#fcfcfb;--surface-2:#efefec;
--border:#dedcd5;--border-strong:#c4c2b8;--text-primary:#0b0b0b;
--text-secondary:#52514e;--text-muted:#84837c;--accent:#2a78d6;--critical:#e34948}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
--surface-0:#121211;--surface-1:#1a1a19;--surface-2:#242422;--border:#35342f;
--border-strong:#4b4a43;--text-primary:#fff;--text-secondary:#c3c2b7;
--text-muted:#8e8d83;--accent:#3987e5;--critical:#e66767}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);
font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:720px;margin:0 auto;padding:48px 16px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.02em}
p.lede{color:var(--text-secondary);margin:0 0 28px}
#drop{border:2px dashed var(--border-strong);border-radius:14px;padding:44px 20px;
text-align:center;background:var(--surface-1);cursor:pointer;transition:.12s}
#drop:hover,#drop.over{border-color:var(--accent);background:var(--surface-2)}
#drop strong{display:block;font-size:16px;margin-bottom:4px}
#drop span{color:var(--text-muted);font-size:13px}
.opts{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0 0;align-items:flex-end}
label{font-size:12px;text-transform:uppercase;letter-spacing:.06em;
color:var(--text-muted);display:block;margin-bottom:5px}
select,input[type=text]{background:var(--surface-1);color:inherit;font:inherit;
font-size:14px;border:1px solid var(--border-strong);border-radius:8px;padding:7px 10px}
button{background:var(--text-primary);color:var(--surface-1);border:0;
border-radius:8px;padding:9px 18px;font:inherit;font-weight:600;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
#status{margin-top:26px;display:none}
#log{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
padding:12px 14px;max-height:280px;overflow:auto;font:12px/1.7 ui-monospace,
SFMono-Regular,Menlo,monospace;color:var(--text-secondary);white-space:pre-wrap}
.done{margin-top:16px;display:flex;gap:10px;flex-wrap:wrap}
.done a{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;
padding:9px 18px;border-radius:8px;font-weight:600;font-size:14px}
.done a.alt{background:var(--surface-1);color:var(--text-primary);
border:1px solid var(--border-strong)}
.err{color:var(--critical);margin-top:12px}
.note{color:var(--text-muted);font-size:12px;margin-top:32px}
</style></head><body><div class="wrap">
<h1>P&amp;ID scanner</h1>
<p class="lede">Upload a P&amp;ID and get back an inventory of every vessel, pump,
compressor, exchanger, valve and instrument on it, with the control loops and a
description of what the drawing shows.</p>

<div id="drop"><strong>Drop a PDF here</strong><span>or click to choose a file</span></div>
<input type="file" id="file" accept="application/pdf,.pdf" hidden>

<div class="opts">
  <div><label for="preset">Detail</label>
    <select id="preset">
      <option value="fast">Fast</option>
      <option value="balanced" selected>Balanced</option>
      <option value="thorough">Thorough</option>
    </select></div>
  <div><label for="pages">Pages</label>
    <input type="text" id="pages" placeholder="all" size="10"></div>
  <div><label for="synth">Narrative</label>
    <select id="synth"><option value="yes" selected>Yes</option>
    <option value="no">Inventory only</option></select></div>
  <button id="go" disabled>Scan</button>
</div>

<div id="status"><div id="log"></div><div id="done" class="done"></div>
<div id="err" class="err"></div></div>

<p class="note">Scans run locally against your own Claude API key. A large sheet
is read in overlapping tiles, so expect a few minutes and a few dollars for a
full E-size drawing.</p>
</div><script>
const drop=document.getElementById('drop'),input=document.getElementById('file'),
go=document.getElementById('go'),statusEl=document.getElementById('status'),
logEl=document.getElementById('log'),doneEl=document.getElementById('done'),
errEl=document.getElementById('err');
let chosen=null;

function pick(f){
 if(!f)return;
 if(!f.name.toLowerCase().endsWith('.pdf')){errEl.textContent='Please choose a PDF.';return}
 chosen=f;errEl.textContent='';
 drop.innerHTML='<strong>'+f.name+'</strong><span>'+(f.size/1048576).toFixed(1)+' MB — click to change</span>';
 go.disabled=false;
}
drop.addEventListener('click',()=>input.click());
input.addEventListener('change',()=>pick(input.files[0]));
['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{
 e.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{
 e.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop',e=>pick(e.dataTransfer.files[0]));

go.addEventListener('click',async()=>{
 if(!chosen)return;
 go.disabled=true;statusEl.style.display='block';doneEl.innerHTML='';
 errEl.textContent='';logEl.textContent='uploading…';
 const fd=new FormData();
 fd.append('file',chosen);
 fd.append('preset',document.getElementById('preset').value);
 fd.append('pages',document.getElementById('pages').value);
 fd.append('synthesize',document.getElementById('synth').value);
 let id;
 try{
  const r=await fetch('/api/scan',{method:'POST',body:fd});
  if(!r.ok){throw new Error((await r.json()).detail||r.statusText)}
  id=(await r.json()).id;
 }catch(e){errEl.textContent=e.message;go.disabled=false;return}

 const poll=setInterval(async()=>{
  const r=await fetch('/api/jobs/'+id);
  if(!r.ok)return;
  const j=await r.json();
  logEl.textContent=j.log.join('\\n');
  logEl.scrollTop=logEl.scrollHeight;
  if(j.state==='done'){
   clearInterval(poll);go.disabled=false;
   doneEl.innerHTML='<a href="/report/'+id+'" target="_blank">Open report</a>'+
    '<a class="alt" href="/api/jobs/'+id+'/markdown" target="_blank">Markdown</a>'+
    '<a class="alt" href="/api/jobs/'+id+'/json" target="_blank">JSON</a>';
  }else if(j.state==='error'){
   clearInterval(poll);go.disabled=false;errEl.textContent=j.error;
  }
 },1200);
});
</script></body></html>
"""
