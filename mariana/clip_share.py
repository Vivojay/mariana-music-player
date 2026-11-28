"""One-file loopback handoff to the operating system's browser share picker."""

from __future__ import annotations

import html
import os
import secrets
import shutil
import stat
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

_TYPES = {".m4a": "audio/mp4", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".mp4": "video/mp4"}
_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Share clip · Mariana</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:#111316;color:#f4f6f2;font:16px/1.55 system-ui,sans-serif}
main{width:min(100%,580px);padding:clamp(24px,6vw,52px);border:1px solid #38413e;border-radius:22px;background:#191e20}
h1{font-size:clamp(1.8rem,6vw,2.8rem);margin:.1em 0}p{color:#d4d9d6;overflow-wrap:anywhere}button,a{font:inherit;color:#9ce7d8}
button,.save{display:inline-block;border-radius:8px;padding:.65rem 1rem;font-weight:650;text-decoration:none}button{border:none;background:#94e2ca;color:#182121;cursor:pointer}
button:disabled{background:#36433e;color:#bdc8c3;cursor:default}.save{border:1px solid #657570}nav{display:flex;flex-wrap:wrap;gap:.75em 1.2em}video,audio{max-width:100%;width:100%;max-height:42vh;border-radius:7px}
</style></head><body><main><h1>Share your clip</h1><p>{{name}}</p><{{player}} controls preload="none" src="file"></{{player}}>
<p><button id="share" disabled>Share file…</button> <a id="save" class="save" href="file" download="{{name}}">Save clip</a></p>
<p role="status" id="status">Preparing sharing options…</p>{{composers}}</main><script>
const button=document.querySelector('#share'),statusLine=document.querySelector('#status'),save=document.querySelector('#save');
let file;
async function prepare(){
  if(!navigator.canShare || !navigator.share){statusLine.textContent='Save the clip to attach it in your app.';return}
  if({{size}}>256*1024*1024){statusLine.textContent='Use Save clip to attach this large file in your app.';return}
  try{
    const response=await fetch('file');
    if(!response.ok)throw Error();
    file=new File([await response.blob()],save.download,{type:'{{mime}}'});
    if(!navigator.canShare({files:[file]})){statusLine.textContent='This browser cannot share this file type. Save it and attach it in your app.';return}
    button.disabled=false;statusLine.textContent='Choose an app from your device to share the file.';
  }catch{statusLine.textContent='The handoff has expired or the file is unavailable. Run clip share again or use the exported file.'}
}
button.addEventListener('click',async()=>{
  button.disabled=true;
  try{await navigator.share({files:[file]});statusLine.textContent='Share request completed. Check the destination app for the next step.'}
  catch(e){statusLine.textContent=e.name==='AbortError'?'Sharing cancelled. Your clip is still here.':'Sharing is unavailable. Save the clip to attach it manually.'}
  finally{button.disabled=false}
});
prepare();
</script></body></html>"""
_COMPOSERS = """<p>To post the video manually, save it and choose the file in a composer.</p><nav aria-label="Video composers">
<a href="https://www.instagram.com/" target="_blank" rel="noreferrer">Instagram</a>
<a href="https://profile.snapchat.com/" target="_blank" rel="noreferrer">Snapchat</a>
<a href="https://www.tiktok.com/upload" target="_blank" rel="noreferrer">TikTok</a>
<a href="https://studio.youtube.com/" target="_blank" rel="noreferrer">YouTube Studio</a></nav>"""


def _signature(details):
    return details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns


def start_handoff(path: Path, lifetime=600, *, recording=False):
    path = path.absolute()
    expected = path.stat(follow_symlinks=False)
    extension = path.suffix.lower()
    mime = _TYPES.get(extension)
    if mime is None and recording:
        mime = {".txt": "text/plain", ".vtt": "text/vtt"}.get(extension)
    if not mime or not stat.S_ISREG(expected.st_mode):
        raise ValueError("Choose a completed Mariana audio or video clip.")
    token = secrets.token_urlsafe(24)
    directory = f"/{token}/"
    filename = html.escape(path.name, quote=True)
    template = _PAGE
    if recording:
        label = "transcript" if mime.startswith("text/") else "recording"
        if label == "transcript":
            template = template.replace('<{{player}} controls preload="none" src="file"></{{player}}>', "")
        template = template.replace("clip", label).replace("Run " + label + " share again", "Reopen sharing in Mariana")
        template = template.replace("{{composers}}", "")
    page = (template.replace("{{composers}}", _COMPOSERS if mime.startswith("video/") else
                          "<p>For a Reel, Spotlight or TikTok video, run <code>clip share --format story</code> with the same marks.</p>")
            .replace("{{player}}", "video" if mime.startswith("video/") else "audio")
            .replace("{{size}}", str(expected.st_size)).replace("{{mime}}", mime)
            .replace("{{name}}", filename)).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        server: ThreadingHTTPServer

        def log_message(self, *args):
            pass  # Do not log the handoff URL.

        def do_HEAD(self):
            self._respond(send_body=False)

        def do_GET(self):
            self._respond(send_body=True)

        def _respond(self, send_body):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or self.path not in {directory, directory + "file"}:
                self.send_error(404)
                return
            document = self.path == directory
            stream = None
            try:
                if not document:
                    stream = path.open("rb")
                    if _signature(os.fstat(stream.fileno())) != _signature(expected):
                        self.send_error(410)
                        return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8" if document else mime)
                self.send_header("Content-Length", str(len(page) if document else expected.st_size))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                                 "style-src 'unsafe-inline'; connect-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                if not document:
                    self.send_header("Content-Disposition", "inline; filename*=UTF-8''" + quote(path.name, safe=""))
                self.end_headers()
                if send_body:
                    if document:
                        self.wfile.write(page)
                    elif stream is not None:
                        shutil.copyfileobj(stream, self.wfile, length=256 * 1024)
            except FileNotFoundError:
                self.send_error(410)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                if stream is not None:
                    stream.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.5
    deadline = time.monotonic() + lifetime

    def run():
        with server:
            while time.monotonic() < deadline:
                server.handle_request()

    threading.Thread(target=run, name="mariana-share", daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}{directory}"


def open_share(path, *, recording=False):
    label = "Clip"
    if recording:
        label = "Transcript" if path.suffix.lower() in {".txt", ".vtt"} else "Recording"
    try:
        url = start_handoff(path, recording=recording)
    except OSError:
        return f"{label} saved at {path}. The local sharing page could not start. Attach the file in your app."
    try:
        opened = webbrowser.open(url, new=2)
    except (OSError, webbrowser.Error):
        opened = False
    instruction = "Choose Share file in your browser" if opened else "Open this address in your browser to share"
    return f"{instruction}: {url}\n{label} saved at {path}. Keep Mariana open while using this ten-minute handoff."
