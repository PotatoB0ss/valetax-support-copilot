"""Minimal agent-facing web page (stdlib only). In production this would be a side panel in the
helpdesk (Zendesk/Freshdesk app) fed by a webhook — same JSON, different shell."""
from __future__ import annotations

import asyncio
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import CONFIGS, Config
from .pipeline import Copilot

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Support Co-pilot</title><style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e3e3de;--ok:#1f7a4d;--warn:#a86400;--bad:#b3261e;--acc:#2a5bd7}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecece8;--mute:#9a9a93;--line:#33332f;--ok:#5cc28e;--warn:#e0a54a;--bad:#ef7a72;--acc:#7da2ff}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px}h1{font-size:20px;margin:0 0 16px}
textarea{width:100%;box-sizing:border-box;min-height:120px;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);font:inherit}
.row{display:flex;gap:8px;align-items:center;margin:8px 0 20px;flex-wrap:wrap}
button,select{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink)}
button{background:var(--acc);color:#fff;border:0;cursor:pointer}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:12px}
.chips span{display:inline-block;border:1px solid var(--line);border-radius:99px;padding:2px 10px;margin:2px 4px 2px 0;font-size:13px}
.k{color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.04em;margin:12px 0 4px}
pre{white-space:pre-wrap;margin:0;font:inherit}.ready{color:var(--ok)}.needs_edit{color:var(--warn)}.blocked,.none{color:var(--bad)}
a{color:var(--acc)}small{color:var(--mute)}
</style></head><body><main><h1>Support Co-pilot</h1>
<textarea id="t" placeholder="Paste a customer ticket…"></textarea>
<div class="row"><select id="c">__OPTS__</select><button id="go">Analyse</button><small id="s"></small></div>
<div id="out"></div></main><script>
const esc=s=>(s??'').toString().replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('go').onclick=async()=>{
 const s=document.getElementById('s');s.textContent='working…';
 const r=await fetch('/api/triage',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({text:document.getElementById('t').value,config:document.getElementById('c').value})});
 const d=await r.json();s.textContent=d.error_http||`$${d.usage.cost_usd.toFixed(5)} · ${d.usage.latency_s}s`;if(d.error_http)return;
 const c=d.classification,rt=d.routing;
 document.getElementById('out').innerHTML=`<div class="card"><div class="chips">
 <span>${esc(c.category)}</span><span>urgency: ${esc(c.urgency)}</span><span>lang: ${esc(c.language)}</span><span>sentiment: ${esc(c.sentiment)}</span>
 ${d.risk_flags.map(f=>`<span>⚑ ${esc(f)}</span>`).join('')}</div>
 <div class="k">Route</div><b>${esc(rt.queue)}</b> · ${esc(rt.priority)} · draft <b class="${esc(rt.draft_status)}">${esc(rt.draft_status)}</b> · mode ${esc(d.response_mode)}
 <ul>${rt.reasons.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>
 ${d.draft_reply?`<div class="card"><div class="k">Draft reply</div><pre>${esc(d.draft_reply)}</pre></div>`:''}
 <div class="card"><div class="k">Sources</div>${d.citations.map(x=>`<div>[${esc(x.chunk_id)}] <a href="${esc(x.url)}" target="_blank">${esc(x.title)}</a></div>`).join('')||'—'}
 ${d.unanswered_questions.length?`<div class="k">Not covered by KB</div><ul>${d.unanswered_questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ul>`:''}
 ${d.issues.length?`<div class="k">Validator</div><ul>${d.issues.map(i=>`<li>${esc(i.severity)} ${esc(i.code)}: ${esc(i.detail)}</li>`).join('')}</ul>`:''}
 ${d.internal_note?`<div class="k">Note for agent</div>${esc(d.internal_note)}`:''}</div>`;};
</script></body></html>"""


def serve(default: Config, port: int = 8000) -> None:
    opts = "".join(f'<option value="{n}"{" selected" if n == default.name else ""}>{html.escape(n)}</option>' for n in CONFIGS)
    page = PAGE.replace("__OPTS__", opts).encode()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])) or b"{}")
            cfg = CONFIGS.get(body.get("config"), default)
            text = (body.get("text") or "").strip()
            res = {"error_http": "empty ticket"} if not text else asyncio.run(Copilot(cfg).process_many([{"id": "web", "text": text}]))[0]
            data = json.dumps(res, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(data)

    print(f"Co-pilot UI on http://127.0.0.1:{port}  (config {default.name})")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
