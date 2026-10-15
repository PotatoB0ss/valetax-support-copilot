"""Business-case calculator: measured eval results x explicit assumptions -> monthly economics per configuration.

  uv run python -m business_case.model            # writes business_case/RESULTS.md and results.json

Method
1. For each eval ticket, estimate agent minutes WITH the co-pilot (conservative):
   - full answer / decline that reached the agent: minutes from the judge's send-readiness grade
   - partial answer: at least `minutes_partial_draft` (agent still researches the missing part)
   - abstain / blocked / error: baseline minus the triage saving
   - escalated to a specialist: baseline minus triage minus acknowledgement saving
2. Average per eval slice, then re-weight slices to the assumed real inbox mix (the eval over-samples risk).
3. Savings = (baseline - with co-pilot) x volume x agent cost/hour.  Costs = measured LLM $/ticket x volume
   + fixed run costs + regression evals. One-off build cost gives the payback period.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
A = json.loads((ROOT / "business_case" / "assumptions.json").read_text())
GOLD = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/eval/tickets.jsonl").read_text().splitlines() if l.strip()}
FTE_HOURS = 160


def minutes_per_slice(outputs: list[dict]) -> dict[str, float]:
    base, md = A["baseline_handle_minutes"], A["minutes_with_draft"]
    acc = defaultdict(list)
    for o in outputs:
        g = GOLD[o["ticket_id"]]
        v = o.get("judge") or {}
        triage = A["triage_minutes_saved_when_no_draft"]
        usable = o["routing"]["draft_status"] in ("ready", "needs_edit") and v.get("send_readiness")
        if o["routing"]["escalated"]:
            # specialist still investigates; we save triage + the acknowledgement (if it is usable)
            m = base - triage - (A["ack_minutes_saved_on_escalation"] if usable else 0)
        elif not usable or o["response_mode"] == "abstain":
            m = base - triage  # nothing to send: the agent researches and writes from scratch
        elif o["response_mode"] == "partial":
            m = max(md[v["send_readiness"]], A["minutes_partial_draft"])
        else:  # answer / decline: judged on send-readiness
            m = md[v["send_readiness"]]
        acc[g["slice"]].append(m)
    return {s: sum(v) / len(v) for s, v in acc.items()}


def economics(cfg: str, metrics: dict, outputs: list[dict], volume: int | None = None, rate: float | None = None) -> dict:
    volume = volume or A["tickets_per_month"]
    rate = rate if rate is not None else A["agent_cost_per_hour_usd"]["base"]
    mps = minutes_per_slice(outputs)
    mix = {s: w for s, w in A["ticket_mix"].items() if s in mps}
    wsum = sum(mix.values())
    minutes_with = sum(mps[s] * w for s, w in mix.items()) / wsum
    saved_min = A["baseline_handle_minutes"] - minutes_with
    hours_saved = saved_min * volume / 60
    llm = metrics["ops"]["cost_per_ticket_usd"] * volume
    eval_cost = A["judge_eval_runs_per_month"] * (metrics["ops"]["cost_per_ticket_usd"] * metrics["n"] + metrics.get("judge_cost_usd", 0))
    fixed = sum(v for k, v in A["fixed_monthly_costs_usd"].items() if not k.startswith("_"))
    total_cost = llm + eval_cost + fixed
    value = hours_saved * rate
    net = value - total_cost
    return {
        "config": cfg,
        "minutes_per_ticket_with_copilot": round(minutes_with, 2),
        "minutes_saved_per_ticket": round(saved_min, 2),
        "hours_saved_per_month": round(hours_saved),
        "fte_equivalent": round(hours_saved / FTE_HOURS, 1),
        "llm_cost_per_month": round(llm, 2),
        "eval_cost_per_month": round(eval_cost, 2),
        "fixed_cost_per_month": fixed,
        "total_cost_per_month": round(total_cost),
        "value_per_month": round(value),
        "net_per_month": round(net),
        "payback_months": round(A["one_off_build_cost_usd"] / net, 1) if net > 0 else None,
        "break_even_agent_rate": round(total_cost / hours_saved, 2) if hours_saved > 0 else None,
        "break_even_volume_at_rate": round(fixed / (saved_min / 60 * rate - metrics["ops"]["cost_per_ticket_usd"])) if saved_min > 0 else None,
    }


def load(cfg: str):
    d = ROOT / "results" / cfg
    m = json.loads((d / "metrics.json").read_text())
    outs = [json.loads(l) for l in (d / "outputs.jsonl").read_text().splitlines() if l.strip()]
    return m, outs


def main():
    summary = json.loads((ROOT / "results" / "summary.json").read_text())
    cfgs = [m["config"] for m in summary if m["config"] != "mock" and "judge" in m]
    rows, sens = [], {}
    for c in cfgs:
        m, outs = load(c)
        e = economics(c, m, outs)
        e["gate"] = "PASS" if not m["gate_failures"] else "FAIL"
        e["usable_rate"] = m["judge"]["usable_rate"]
        e["escalation_recall"] = m["escalation"]["recall"]
        rows.append(e)
        sens[c] = {
            "rate": {k: economics(c, m, outs, rate=v)["net_per_month"] for k, v in A["agent_cost_per_hour_usd"].items() if not k.startswith("_")},
            "volume": {v: economics(c, m, outs, volume=v)["net_per_month"] for v in (5000, 10000, 20000, 50000, 100000)},
        }
    (ROOT / "business_case" / "results.json").write_text(json.dumps({"rows": rows, "sensitivity": sens}, indent=2) + "\n")

    L = ["# Business-case numbers (generated)\n",
         f"Volume {A['tickets_per_month']:,}/month · baseline {A['baseline_handle_minutes']} min/ticket · agent ${A['agent_cost_per_hour_usd']['base']}/h (base case). "
         "Measured: draft quality (judge), routing, $/ticket. Assumed: see assumptions.json.\n",
         "| Config | Gate | Usable drafts | Min saved / ticket | Hours saved / mo | FTE | LLM $/mo | Total cost $/mo | Value $/mo | Net $/mo | Payback (mo) | Break-even agent $/h |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['config']} | {r['gate']} | {100*r['usable_rate']:.0f}% | {r['minutes_saved_per_ticket']} | {r['hours_saved_per_month']:,} | {r['fte_equivalent']} | "
                 f"{r['llm_cost_per_month']:,.0f} | {r['total_cost_per_month']:,} | {r['value_per_month']:,} | {r['net_per_month']:,} | {r['payback_months'] or '–'} | {r['break_even_agent_rate']} |")
    L += ["\n## Sensitivity: net $/month\n", "| Config | " + " | ".join(f"agent ${v}/h" for k, v in A["agent_cost_per_hour_usd"].items() if not k.startswith("_"))
          + " | " + " | ".join(f"{v // 1000}k tickets" for v in (5000, 10000, 20000, 50000, 100000)) + " |", "|---|" + "---|" * 8]
    for c, s in sens.items():
        L.append(f"| {c} | " + " | ".join(f"{v:,}" for v in s["rate"].values()) + " | " + " | ".join(f"{v:,}" for v in s["volume"].values()) + " |")
    (ROOT / "business_case" / "RESULTS.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
