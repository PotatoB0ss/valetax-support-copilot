"""Phase 2 simulation: what happens to retrieval and prompt cost as the KB + SOPs grow?

We pad the real 24-chunk KB with synthetic, deliberately *confusable* SOP chunks (same vocabulary:
deposit, withdrawal, verification, account, fees, documents...) and measure, on the English eval tickets
that have gold chunks:
  - BM25 recall@k of the gold chunks (does the right page still make it into the prompt?)
  - prompt size and $/ticket for "stuff the whole KB" vs "top-k retrieval"

  uv run python -m evals.scale_sim     -> results/scale_sim.md
No API calls; deterministic (seeded).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from copilot.config import PRICES
from copilot.kb import Chunk, load_chunks
from copilot.retrieval import BM25

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ["deposit", "withdrawal", "verification", "account", "bonus", "transfer", "card", "crypto wallet", "bank wire",
          "e-wallet", "documents", "IB commission", "copy trading", "swap", "MT5 password", "leverage change", "refund", "chargeback"]
ASPECTS = ["limits", "fees", "processing time", "rejection reasons", "required documents", "country restrictions",
           "currency conversion", "status meanings", "escalation steps", "cut-off times", "minimum amount", "history and statements"]
REGIONS = ["Indonesia", "Malaysia", "Vietnam", "Nigeria", "Egypt", "UAE", "Brazil", "Mexico", "India", "Pakistan", "Kenya", "Thailand"]
VERBS = ["deposit", "withdraw", "verify", "open", "transfer", "credit", "approve", "reject", "review", "process"]


def synthetic_chunks(n: int, seed: int = 7) -> list[Chunk]:
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        topic, aspect, region = rnd.choice(TOPICS), rnd.choice(ASPECTS), rnd.choice(REGIONS)
        words = " ".join(rnd.choice(VERBS + TOPICS + ASPECTS) for _ in range(40))
        text = (f"SOP {i}: {topic} {aspect} for clients in {region}. Agents must {rnd.choice(VERBS)} the {topic} request "
                f"after checking the {rnd.choice(ASPECTS)} in the back office. {words}.")
        out.append(Chunk(id=f"sop/{i}", title=f"{topic.title()} — {aspect} ({region})", text=text, urls=["internal"], pages=["sop"], kind="sop"))
    return out


def tokens(chunks: list[Chunk]) -> int:
    return sum(len(c.render()) for c in chunks) // 4  # ~4 chars/token for English


def main():
    real = load_chunks()
    gold = [json.loads(l) for l in (ROOT / "data/eval/tickets.jsonl").read_text().splitlines() if l.strip()]
    qs = [g for g in gold if g["lang"] == "en" and g["gold"]]
    p = PRICES["claude-sonnet-5-5"]
    base_prompt = 1700  # rules + instructions, measured order of magnitude
    lines = ["# Phase 2 simulation: KB growth\n",
             f"{len(qs)} English eval tickets with gold chunks; KB padded with confusable synthetic SOP chunks. "
             "Cost = Sonnet 5.5 input only; 'full, cached' assumes the KB prefix is a cache hit (0.1x), retrieval prompts vary per ticket so are uncached.\n",
             "| KB chunks | KB tokens | recall@3 | recall@6 | recall@12 | full KB $/ticket (cached) | top-6 $/ticket | fits 1M context? |",
             "|---|---|---|---|---|---|---|---|"]
    for n_extra in (0, 200, 1000, 5000, 20000):
        kb = real + synthetic_chunks(n_extra)
        bm = BM25(kb)
        rec = {}
        for k in (3, 6, 12):
            r = []
            for g in qs:
                got = {c.id for c in bm.search(g["text"], k)}
                r.append(len(got & set(g["gold"])) / len(g["gold"]))
            rec[k] = sum(r) / len(r)
        kt = tokens(kb)
        full_cached = ((base_prompt + kt) * p["cache_read"] + 150 * p["in"]) / 1e6
        top6 = ((base_prompt + 6 * 120 + 150) * p["in"]) / 1e6
        lines.append(f"| {len(kb):,} | {kt:,} | {rec[3]:.0%} | {rec[6]:.0%} | {rec[12]:.0%} | ${full_cached:.4f} | ${top6:.4f} | {'yes' if kt < 900_000 else 'no'} |")
    lines += ["",
              "Reading: with today's 24 chunks, stuffing the whole KB is both cheaper (cache) and risk-free (recall 100% by construction) -> Phase 1 choice.",
              "As SOPs grow into the thousands of chunks, the cached full prompt grows linearly in cost and latency and eventually stops fitting, while "
              "lexical recall drops on confusable content -> Phase 2 switches to triage + retrieval, and recall@k becomes a gated eval metric. "
              "Upgrade path for recall: hybrid BM25 + multilingual embeddings, metadata filters (category/region), and a reranker."]
    (ROOT / "results" / "scale_sim.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
