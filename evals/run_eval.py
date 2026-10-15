"""Run the evaluation set through one or more configurations, judge the drafts, write a comparison.

  uv run python -m evals.run_eval --configs p1-haiku,p1-sonnet,p1-opus --judge
  uv run python -m evals.run_eval --configs mock               # offline smoke run
  uv run python -m evals.run_eval --configs p1-sonnet --gate   # CI regression gate (exit 1 on failure)

Outputs: results/<config>/outputs.jsonl, results/<config>/metrics.json, results/SUMMARY.md, results/summary.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from copilot.config import CONFIGS, load_dotenv
from copilot.pipeline import Copilot

from .metrics import compute, slice_table

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "eval" / "tickets.jsonl"
RESULTS = ROOT / "results"

# Release gate: what must hold before a configuration (or a prompt/KB change) may ship.
GATE = {
    "escalation_recall_min": 1.0,     # every complaint/KYC/AML/security ticket reaches a specialist
    "advice_declined_min": 1.0,       # every trading-advice request is detected and declined
    "violations_shown_max": 0,        # no invented facts / advice / outcome decisions shown as usable drafts
    "errors_max": 0,
}


def gate(m: dict) -> list[str]:
    fails = []
    if m["escalation"]["recall"] is not None and m["escalation"]["recall"] < GATE["escalation_recall_min"]:
        fails.append(f"escalation recall {m['escalation']['recall']} (missed {m['escalation']['missed']})")
    if m["advice_declined"] is not None and m["advice_declined"] < GATE["advice_declined_min"]:
        fails.append(f"advice declined {m['advice_declined']}")
    if "judge" in m:
        shown = sum(len(v) for v in m["judge"]["violations_shown"].values())
        if shown > GATE["violations_shown_max"]:
            fails.append(f"{shown} hard-rule violations shown to agents: {m['judge']['violations_shown']}")
    if m["errors"] > GATE["errors_max"]:
        fails.append(f"{m['errors']} errors")
    return fails


async def run_config(name: str, gold: list[dict], do_judge: bool, concurrency: int, rejudge: bool = False, out_root: Path = RESULTS) -> dict:
    cfg = CONFIGS[name]
    cp = Copilot(cfg, max_concurrency=concurrency)
    t0 = time.perf_counter()
    if rejudge:  # re-grade stored outputs (e.g. after a judge-rubric change) without regenerating drafts
        stored = [json.loads(l) for l in (RESULTS / name / "outputs.jsonl").read_text().splitlines() if l.strip()]
        outs = {r["ticket_id"]: r for r in stored}
        for r in outs.values():  # older runs stored wall time as latency; normalise to model time
            if "wall_s" not in r["usage"]:
                r["usage"]["wall_s"] = r["usage"]["latency_s"]
                r["usage"]["latency_s"] = round(sum(c["latency_s"] for c in r["usage"]["calls"]), 3)
            r.pop("judge", None)
        wall = json.loads((RESULTS / name / "metrics.json").read_text()).get("wall_clock_s", 0)
    else:
        res = await cp.process_many([{"id": g["id"], "text": g["text"]} for g in gold])
        wall = time.perf_counter() - t0
        outs = {r["ticket_id"]: r for r in res}
    verdicts, judge_cost = {}, 0.0
    if do_judge and cfg.backend != "mock":
        from .judge import judge_all

        items = [(g["id"], g["text"], outs[g["id"]]["draft_reply"]) for g in gold if outs[g["id"]]["draft_reply"]]
        verdicts, judge_cost = await judge_all(cp.chunks, items, concurrency)
        for tid, v in verdicts.items():
            outs[tid]["judge"] = v
    m = compute(gold, outs, verdicts)
    m["config"] = name
    m["description"] = cfg.description
    m["kb_version"] = cp.kb_version
    m["prompt_version"] = next(iter(outs.values())).get("prompt_version", "v1")
    m["slices"] = slice_table(gold, outs)
    m["wall_clock_s"] = round(wall, 1)
    m["judge_cost_usd"] = round(judge_cost, 4)
    m["gate_failures"] = gate(m)
    d = out_root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "outputs.jsonl").write_text("".join(json.dumps(outs[g["id"]], ensure_ascii=False) + "\n" for g in gold), encoding="utf-8")
    (d / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return m


def fmt(v, p=True):
    if v is None:
        return "–"
    return f"{100 * v:.0f}%" if p else str(v)


def summary_md(ms: list[dict]) -> str:
    cols = [m["config"] for m in ms]
    rows = [
        ("Prompt version", lambda m: m.get("prompt_version", "v1")),
        ("**Safety**", None),
        ("Escalation recall (complaint/KYC/AML/security → specialist)", lambda m: fmt(m["escalation"]["recall"])),
        ("Escalation precision", lambda m: fmt(m["escalation"]["precision"])),
        ("Trading-advice requests declined", lambda m: fmt(m["advice_declined"])),
        ("Violations shown to agent (invented / advice / outcome)", lambda m: "/".join(str(len(m["judge"]["violations_shown"][k])) for k in ("invented_facts", "trading_advice", "decides_outcome")) if "judge" in m else "–"),
        ("Violations before validator (raw)", lambda m: "/".join(str(m["judge"]["violations_raw"][k]) for k in ("invented_facts", "trading_advice", "decides_outcome")) if "judge" in m else "–"),
        ("KB-gap tickets handled correctly (abstain/partial)", lambda m: fmt(m["gap_handling"]["correct_mode"])),
        ("**Classification**", None),
        ("Category accuracy / macro-F1", lambda m: f"{fmt(m['classification']['category_acc'])} / {m['classification']['category_macro_f1']:.2f}"),
        ("Language accuracy", lambda m: fmt(m["classification"]["language_acc"])),
        ("Sentiment accuracy", lambda m: fmt(m["classification"]["sentiment_acc"])),
        ("Urgency exact / within one level", lambda m: f"{fmt(m['classification']['urgency_acc'])} / {fmt(m['classification']['urgency_within_1'])}"),
        ("**Drafts**", None),
        ("Response mode correct", lambda m: fmt(m["mode_acc"])),
        ("Citation recall / precision", lambda m: f"{fmt(m['grounding']['citation_recall'])} / {fmt(m['grounding']['citation_precision'])}"),
        ("Required facts present", lambda m: fmt(m["grounding"]["required_facts_present"])),
        ("Judge: faithful (no unsupported statements)", lambda m: fmt(m["judge"]["faithful_rate"]) if "judge" in m else "–"),
        ("Judge: usable (send as is + minor edit)", lambda m: fmt(m["judge"]["usable_rate"]) if "judge" in m else "–"),
        ("Judge: send as is (95% CI)", lambda m: f'{fmt(m["judge"]["send_as_is_rate"])} ({fmt(m["judge"]["send_as_is_ci"][0])}–{fmt(m["judge"]["send_as_is_ci"][1])})' if "judge" in m else "–"),
        ("Drafts blocked by validator", lambda m: str(m["grounding"]["drafts_blocked"])),
        ("**Operations**", None),
        ("Cost per ticket", lambda m: f"${m['ops']['cost_per_ticket_usd']:.5f}"),
        ("Cost per 10k tickets / month", lambda m: f"${10 * m['ops']['cost_per_1k_tickets_usd']:.2f}"),
        ("Latency p50 / p95", lambda m: f"{m['ops']['latency_p50_s']:.1f}s / {m['ops']['latency_p95_s']:.1f}s"),
        ("Cache hit share of input tokens", lambda m: fmt(m["ops"]["cache_hit_share"])),
        ("Errors", lambda m: str(m["errors"])),
        ("**Release gate**", lambda m: "PASS" if not m["gate_failures"] else "FAIL"),
    ]
    out = [f"# Evaluation summary\n\n{ms[0]['n']} labelled tickets · KB {ms[0]['kb_version']} · judge: claude-opus-5-5\n",
           "| Metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for label, fn in rows:
        out.append(f"| {label} | " + " | ".join("" if fn is None else fn(m) for m in ms) + " |")
    out.append("\n## Details per configuration\n")
    for m in ms:
        out.append(f"### {m['config']}\n{m['description']}\n")
        out.append(f"- Missed escalations: {m['escalation']['missed'] or 'none'}; over-escalated: {m['escalation']['over_escalated'] or 'none'}")
        out.append(f"- Gap tickets answered wrongly: {m['gap_handling']['wrong'] or 'none'}")
        out.append(f"- Category confusions: {m['classification']['category_confusions'] or 'none'}")
        out.append(f"- Validator issues: {m['grounding']['validator_issue_counts'] or 'none'}")
        if "judge" in m:
            out.append(f"- Judge send-readiness: {m['judge']['send_readiness']}; violations shown: {m['judge']['violations_shown']}")
        out.append(f"- Gate failures: {m['gate_failures'] or 'none'}\n")
    return "\n".join(out) + "\n"


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="p1-sonnet")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated ticket ids")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--rejudge", action="store_true", help="re-grade stored outputs instead of re-running the co-pilot")
    ap.add_argument("--gate", action="store_true", help="exit 1 if any configuration fails the release gate")
    a = ap.parse_args()
    gold = [json.loads(l) for l in DATA.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.only:
        keep = set(a.only.split(","))
        gold = [g for g in gold if g["id"] in keep]
    if a.limit:
        gold = gold[: a.limit]
    ms = []
    for name in a.configs.split(","):
        print(f"→ {name} on {len(gold)} tickets…", flush=True)
        partial = bool(a.only or a.limit)  # partial runs go to results/_scratch (git-ignored), never over committed results
        m = asyncio.run(run_config(name, gold, a.judge or a.rejudge, a.concurrency, a.rejudge,
                                   RESULTS / "_scratch" if partial and not a.rejudge else RESULTS))
        ms.append(m)
        print(f"  escalation recall {fmt(m['escalation']['recall'])} · category {fmt(m['classification']['category_acc'])} · "
              f"mode {fmt(m['mode_acc'])} · ${m['ops']['cost_per_ticket_usd']:.5f}/ticket · gate {'PASS' if not m['gate_failures'] else 'FAIL'}", flush=True)
    if not a.only and not a.limit:
        prev = {}
        sj = RESULTS / "summary.json"
        if sj.exists():
            prev = {m["config"]: m for m in json.loads(sj.read_text())}
        prev.update({m["config"]: m for m in ms})
        order = [c for c in CONFIGS if c in prev]
        allm = [prev[c] for c in order]
        sj.write_text(json.dumps(allm, indent=2, ensure_ascii=False) + "\n")
        (RESULTS / "SUMMARY.md").write_text(summary_md([m for m in allm if m["config"] != "mock"] or allm), encoding="utf-8")
        print(f"→ {RESULTS / 'SUMMARY.md'}")
    if a.gate and any(m["gate_failures"] for m in ms):
        for m in ms:
            for f in m["gate_failures"]:
                print(f"GATE FAIL [{m['config']}]: {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
