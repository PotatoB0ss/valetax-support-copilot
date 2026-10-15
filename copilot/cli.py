"""CLI.

  copilot triage "ticket text"            # one ticket, human-readable card
  copilot triage --json "ticket text"     # one ticket, full JSON
  copilot batch tickets.jsonl -o out.jsonl  # many tickets ({"id","text"} per line), concurrent
  copilot serve                           # minimal web page on http://127.0.0.1:8000
  copilot kb                              # rebuild KB chunks from data/kb_raw snapshots
  copilot configs                         # list run configurations
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import CONFIGS, DEFAULT_CONFIG, load_dotenv
from .pipeline import Copilot


def render_card(r: dict) -> str:
    c, rt = r["classification"], r["routing"]
    lines = [
        f"── Ticket {r['ticket_id'] or ''}  [{r['config']} · kb {r['kb_version']}]",
        f"Category: {c['category']}   Urgency: {c['urgency']}   Language: {c['language']}   Sentiment: {c['sentiment']}",
        f"Risk flags: {', '.join(f'{f} ({'+'.join(s)})' for f, s in r['risk_flag_sources'].items()) or 'none'}",
        f"Route: {rt['queue']}  priority {rt['priority']}  draft: {rt['draft_status']}  mode: {r['response_mode']}",
    ]
    lines += [f"  · {x}" for x in rt["reasons"]]
    if r["draft_reply"]:
        lines += ["", "Draft reply:", *("  " + l for l in r["draft_reply"].splitlines())]
    if r["citations"]:
        lines += ["", "Sources:"] + [f"  [{x['chunk_id']}] {x['title']} — {x['url']}" for x in r["citations"]]
    if r["unanswered_questions"]:
        lines += ["", "Not covered by KB:"] + [f"  - {q}" for q in r["unanswered_questions"]]
    if r["issues"]:
        lines += ["", "Validator:"] + [f"  {i['severity'].upper()} {i['code']}: {i['detail']}" for i in r["issues"]]
    if r["internal_note"]:
        lines += ["", f"Note for agent: {r['internal_note']}"]
    u = r["usage"]
    lines += ["", f"cost ${u['cost_usd']:.5f} · {u['latency_s']:.1f}s · calls: {', '.join(c['model'] for c in u['calls'])}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="copilot", description="Support-ticket co-pilot")
    ap.add_argument("--config", default=DEFAULT_CONFIG, choices=sorted(CONFIGS))
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("triage")
    t.add_argument("text", nargs="?", help="ticket text (or stdin)")
    t.add_argument("--json", action="store_true")
    b = sub.add_parser("batch")
    b.add_argument("path")
    b.add_argument("-o", "--out", default="-")
    b.add_argument("--concurrency", type=int, default=8)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("kb")
    sub.add_parser("configs")
    a = ap.parse_args(argv)
    cfg = CONFIGS[a.config]

    if a.cmd == "configs":
        for c in CONFIGS.values():
            print(f"{c.name:20s} {c.description}")
    elif a.cmd == "kb":
        from .kb import build_chunks, kb_version, save_chunks

        cs = build_chunks()
        save_chunks(cs)
        print(f"{len(cs)} chunks, kb_version={kb_version(cs)}")
    elif a.cmd == "triage":
        text = a.text or sys.stdin.read()
        r = asyncio.run(Copilot(cfg).process_many([{"id": "cli", "text": text.strip()}]))[0]
        print(json.dumps(r, indent=2, ensure_ascii=False) if a.json else render_card(r))
    elif a.cmd == "batch":
        tickets = [json.loads(l) for l in Path(a.path).read_text().splitlines() if l.strip()]
        res = asyncio.run(Copilot(cfg, max_concurrency=a.concurrency).process_many(tickets))
        out = sys.stdout if a.out == "-" else open(a.out, "w")
        for r in res:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
        if out is not sys.stdout:
            out.close()
            print(f"{len(res)} tickets -> {a.out}  total ${sum(r['usage']['cost_usd'] for r in res):.4f}")
    elif a.cmd == "serve":
        from .web import serve

        serve(cfg, a.port)


if __name__ == "__main__":
    main()
