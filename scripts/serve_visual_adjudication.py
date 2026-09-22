#!/usr/bin/env python3
"""Serve trusted-local post-blind reconciliation/adjudication on loopback."""
from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import subprocess
from urllib.parse import unquote, urlsplit

from visual_adjudication import AdjudicationStore, sha256_file


PAGE = r'''<!doctype html><meta charset="utf-8"><title>Visual adjudication</title>
<style>
body{font:16px system-ui;max-width:1200px;margin:2em auto;padding:0 1em}
img{max-width:100%;max-height:52vh}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;padding:1em}
textarea,input,select,button{font:inherit;margin:.4em;padding:.45em}
textarea{width:100%;min-height:70px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:1em}
#message{color:#a00}
</style>
<h1>Post-blind visual adjudication</h1>
<p>The blind first pass is immutable. Automated source identities are pseudonymous until explicitly revealed. This surface writes adjudication events only; it does not create gold labels or accept candidates.</p>
<label>Asset <select id="asset"></select></label>
<p id="identity"></p><img id="image" alt="Image under adjudication">
<div class="grid"><section><h2>Blind human evidence</h2><pre id="human"></pre></section><section><h2>Seed / automated evidence</h2><pre id="evidence"></pre></section></div>
<button id="reveal">Reveal automated source identities for this asset</button>
<pre id="source-map" hidden></pre>
<h2>Record adjudication</h2>
<form id="form">
<label>Subject type <select id="subject-type"><option value="concept_id">Canonical concept ID</option><option value="human_statement">Human statement</option></select></label>
<label>Subject <input id="subject" size="70" required></label>
<label>Decision <select id="decision"><option>supported</option><option>contradicted</option><option>unknown</option><option>abstain</option><option>needs_followup</option></select></label>
<label>Evidence references (one per line)<textarea id="refs"></textarea></label>
<label>Note<textarea id="note"></textarea></label>
<button>Append adjudication event</button>
</form>
<h2>Adjudication events for this asset</h2><pre id="history"></pre><p id="message" role="status"></p>
<script>
const token=location.hash.slice(1)||sessionStorage.getItem('adj-token')||'';sessionStorage.setItem('adj-token',token);history.replaceState(null,'',location.pathname);
const $=id=>document.getElementById(id);let state;let imageURL;
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'X-Adjudication-Token':token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const data=await r.json();if(!r.ok)throw Error(data.error);return data;}
async function refresh(selected){state=await api('/api/state');$('asset').replaceChildren(...state.assets.map((a,i)=>{const o=document.createElement('option');o.value=a.asset_id;o.textContent=(i+1)+'. '+a.asset_id;return o;}));$('asset').value=selected||state.assets[0].asset_id;await show();}
async function show(){try{const id=$('asset').value;const view=await api('/api/view/'+encodeURIComponent(id));$('identity').textContent='Asset '+id+' · SHA-256 '+view.sha256;$('human').textContent=JSON.stringify(view.blind_human,null,2);$('evidence').textContent=JSON.stringify({seed_reference:view.seed_reference,automated:view.automated,comparison:view.comparison},null,2);$('source-map').hidden=!view.source_identity_revealed;$('source-map').textContent=view.source_identity_map?JSON.stringify(view.source_identity_map,null,2):'';$('history').textContent=JSON.stringify(state.events.filter(e=>e.asset_id===id),null,2);const r=await fetch('/image/'+encodeURIComponent(id),{headers:{'X-Adjudication-Token':token}});if(!r.ok)throw Error('image verification failed');const blob=await r.blob();if(imageURL)URL.revokeObjectURL(imageURL);imageURL=URL.createObjectURL(blob);$('image').src=imageURL;$('message').textContent='';}catch(e){$('message').textContent=e.message;}}
$('asset').onchange=show;
$('reveal').onclick=async()=>{try{const id=$('asset').value;const key='reveal-'+id;await api('/api/reveal',{asset_id:id,idempotency_key:key});state=await api('/api/state');await show();}catch(e){$('message').textContent=e.message;}};
$('form').onsubmit=async e=>{e.preventDefault();try{const id=$('asset').value;const key=crypto.randomUUID();await api('/api/adjudicate',{asset_id:id,subject_type:$('subject-type').value,subject:$('subject').value,decision:$('decision').value,evidence_refs:$('refs').value.split('\n').map(s=>s.trim()).filter(Boolean),note:$('note').value,idempotency_key:key});state=await api('/api/state');$('subject').value='';$('refs').value='';$('note').value='';await show();}catch(e){$('message').textContent=e.message;}};
refresh().catch(e=>$('message').textContent=e.message);
</script>'''


def _benchmark_images(benchmark_path: str | Path, image_root: str | Path, store: AdjudicationStore) -> dict[str, Path]:
    benchmark_path = Path(benchmark_path)
    if sha256_file(benchmark_path) != store.blind["session"].get("benchmark_sha256"):
        raise ValueError("benchmark SHA-256 does not match blind session")
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    root = Path(image_root).resolve()
    expected = {row["asset_id"]: row["sha256"] for row in store.blind["assets"]}
    images: dict[str, Path] = {}
    for entry in benchmark.get("assets", []):
        meta = entry.get("asset", entry)
        asset_id = str(meta.get("benchmark_asset_id") or entry.get("benchmark_asset_id") or "")
        filename = meta.get("source_filename") or meta.get("filename") or entry.get("source_filename")
        sha = str(meta.get("sha256") or entry.get("sha256") or "")
        if asset_id not in expected:
            continue
        if sha != expected[asset_id] or not filename:
            raise ValueError("benchmark/image identity mismatch")
        path = (root / str(filename)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("image outside root or missing")
        if sha256_file(path) != sha:
            raise ValueError("image SHA-256 mismatch")
        images[asset_id] = path
    if set(images) != set(expected):
        raise ValueError("benchmark image set does not match blind session")
    return images


def _mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")


def make_server(store: AdjudicationStore, images: dict[str, Path], port: int = 8766):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, code, body, content_type="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, auth=True):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != urlsplit(origin).netloc or self.headers.get("Origin", origin) != origin:
                self.respond(403, {"error": "loopback same-origin access required"})
                return False
            if auth and not hmac.compare_digest(self.headers.get("X-Adjudication-Token", ""), token):
                self.respond(403, {"error": "open the local launch URL with its session token"})
                return False
            return True

        def do_GET(self):
            if not self.allowed(auth=self.path != "/"):
                return
            try:
                if self.path == "/":
                    self.respond(200, PAGE.encode(), "text/html; charset=utf-8")
                elif self.path == "/api/state":
                    events = store.events()
                    self.respond(200, {
                        "assets": store.blind["assets"],
                        "events": events,
                        "ground_truth": False,
                        "gold_promotion_available": False,
                    })
                elif self.path.startswith("/api/view/"):
                    asset_id = unquote(self.path.removeprefix("/api/view/"))
                    self.respond(200, store.view(asset_id))
                elif self.path.startswith("/image/"):
                    asset_id = unquote(self.path.removeprefix("/image/"))
                    if asset_id not in images:
                        raise ValueError("unknown asset")
                    path = images[asset_id]
                    data = path.read_bytes()
                    expected = next(x["sha256"] for x in store.blind["assets"] if x["asset_id"] == asset_id)
                    if hashlib.sha256(data).hexdigest() != expected:
                        raise ValueError("image SHA-256 mismatch")
                    self.respond(200, data, _mime(path))
                else:
                    self.respond(404, {"error": "not found"})
            except (ValueError, KeyError, OSError) as exc:
                self.respond(400, {"error": str(exc)})

        def do_POST(self):
            if not self.allowed():
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 512000:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("expected an object")
                if self.path == "/api/reveal":
                    result = store.reveal_source_identities(payload.get("asset_id"), payload.get("idempotency_key"))
                elif self.path == "/api/adjudicate":
                    result = store.record(payload)
                else:
                    self.respond(404, {"error": "not found"})
                    return
                self.respond(200, result)
            except (ValueError, KeyError, OSError) as exc:
                self.respond(400, {"error": str(exc)})

    import hashlib
    return HTTPServer(("127.0.0.1", port), Handler), token


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ["blind-session", "blind-ledger", "review-queue", "benchmark", "image-root", "output-dir", "reviewer"]:
        ap.add_argument("--" + name, required=True)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--open-browser", action="store_true")
    args = ap.parse_args()

    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
    ).strip()
    store = AdjudicationStore(
        blind_session=args.blind_session,
        blind_ledger=args.blind_ledger,
        reconciliation_queue=args.review_queue,
        directory=args.output_dir,
        reviewer=args.reviewer,
        implementation_revision=revision,
    )
    images = _benchmark_images(args.benchmark, args.image_root, store)
    server, token = make_server(store, images, args.port)
    url = f"http://127.0.0.1:{server.server_port}/#{token}"
    print(f"Open {url}", flush=True)
    if args.open_browser:
        import webbrowser
        webbrowser.open(url)
    print("Trusted-local adjudication session. Stop with Ctrl-C.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
