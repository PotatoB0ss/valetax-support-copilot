# Architecture: Phase 1 (ship ASAP) → Phase 2 (scale)

## Principles

1. **Co-pilot, not autopilot.** In Phase 1 nothing is sent without an agent. Risk is bounded by a human, and every edit an agent makes becomes a quality signal.
2. **The LLM proposes, code decides.** Classification and drafting are probabilistic. Routing, validation and the release gate are deterministic code that Compliance can read line by line (`routing.py`, `guardrails.py`).
3. **Defence in depth for the hard rules.** Each rule is enforced by at least two independent layers:

| Hard rule | Layer 1 (prompt) | Layer 2 (code, pre) | Layer 3 (code, post) | Layer 4 (process) |
|---|---|---|---|---|
| No trading advice | explicit rule + `decline` mode | multilingual keyword rules OR-ed into flags | advice-phrase detector blocks the draft | agent review; eval gate = 100% declined |
| Never decide complaint/KYC/AML | acknowledgement-only instruction | keyword rules → specialist queue even if the LLM misses | outcome-promise detector blocks the draft | specialist queue owns the decision |
| Never invent policy/fees/timelines | quote-every-claim contract (`claims[]`) | KB is the only context; ticket is untrusted data | quotes must be verbatim in the cited chunk, and every number must appear in a cited chunk or the ticket | judge faithfulness in eval; gate = 0 shown violations |

4. **Everything measurable.** Every output records `config`, `kb_version`, model, tokens, cost, latency and validator issues. Eval and business case are computed from the same files.

## Phase 1: what ships in week 1

```
helpdesk webhook (new ticket) ─▶ co-pilot service ─▶ internal note + tags + queue on the ticket
                                    │
        rules (regex, 0 ms) ────────┤
        1 Claude call (structured JSON; rules + full KB in cached system prompt)
        validator (citations, quotes, numbers, advice, outcome promises)
        router (deterministic) ─────┘
```

- **One LLM call per ticket.** The 4 pages are ~1.8k tokens, so the whole KB goes into the system prompt and is prompt-cached. Retrieval can't miss, and there's no vector DB to run. `config: p1-*`.
- **Structured outputs** (JSON schema enforced by the API). No parsing heuristics. The schema forces `claims[]` with verbatim quotes, which is what makes grounding checkable by code.
- **Output to the agent**: classification chips, risk flags (with source: llm / rules), queue + priority + reasons, a draft in the customer's language, sources with URLs, "not covered by KB" list, validator warnings. CLI and a minimal web page are included. In production the same JSON goes into a helpdesk sidebar app (Zendesk/Freshdesk/Intercom) via webhook.
- **Failure mode = human.** API errors, refusals, `max_tokens` and validation blocks all route the ticket to `agent_manual`. A ticket is never lost or auto-answered. On Sonnet/Opus, server-side refusal fallbacks (`fallbacks: "default"`) re-run a safety-classifier decline on a fallback model inside the same call.
- **Model choice is a config.** It is decided by the eval + business case (`results/SUMMARY.md`, `business_case/RESULTS.md`), not by taste.

What is mocked or stubbed in this repo, and what the real version does:

| Stub here | Real version |
|---|---|
| CLI / stdlib web page | Helpdesk sidebar app; webhook on ticket-created; writes internal note + tags + assignee group |
| KB = 4 HTML snapshots parsed at build time | Scheduled crawler / CMS export → chunker → content-hash diff → re-index + re-run eval when `kb_version` changes |
| Synthetic labelled eval set (83 tickets) | 300–500 real historical tickets, PII-redacted, double-labelled by support leads; refreshed monthly from agent edits |
| LLM judge only | Judge calibrated against ~50 human ratings; online metric = agent edit distance and "sent as is" rate |
| No PII handling | Redact card numbers/IDs before the LLM call (regex + allow-list). The provider must offer ZDR/DPA. Logs keep the hash, not the text |

## Phase 2: scale (10k → 100k tickets/month, KB → hundreds of pages + SOPs)

Volume itself is not the hard part: 10k tickets/month is about 14 per hour. At measured cost and latency this is
cents per hour and needs no special infrastructure. Phase 2 is about the **KB and SOPs growing** and the
**operational loop**.

```
ticket ─▶ triage (Haiku 5.5: flags, category, language, English search query)
            │  specialist flags → acknowledgement template + specialist queue (cheap path)
            ▼
         retrieval: hybrid BM25 + multilingual embeddings, filtered by category/region/effective-date, top-k
            ▼
         draft (model chosen by eval; cascade to a stronger model only on validation failure)
            ▼
         validator ─▶ router ─▶ helpdesk
```

| Concern | What changes | Where in repo |
|---|---|---|
| KB outgrows the prompt | `staged` mode: triage → retrieval → draft. The triage step writes an English query, which makes lexical retrieval work for RU/AR/ES/VI tickets against an English KB. | `config.py: p2-staged`, `retrieval.py` |
| Retrieval quality | recall@k becomes a gated eval metric. Simulation shows the crossover (full KB ≈ cheaper below ~200 chunks; beyond that, top-k wins and the full prompt eventually exceeds context). | `evals/scale_sim.py`, `results/scale_sim.md` |
| Conflicting / outdated SOPs | Chunks carry `sha` + `kb_version`. Production adds `effective_from`, `owner`, `locale`, and a conflict detector (same question, different answers → content backlog). | `kb.py`, `docs/KB_AUDIT.md` |
| Cost at volume | Prompt caching on the stable prefix. Use the 1-hour TTL when traffic is under ~12 tickets per 5 minutes: at 14 tickets/hour the default 5-minute cache often expires between tickets. Cheap triage first, then cascade (cheap model, escalate only blocked drafts). Batch API (−50%) for non-urgent backlog re-processing and evals. | `llm.py`, `config.py: p1-haiku-cascade` |
| Throughput / rate limits | Async workers behind a queue (SQS/Redis), concurrency semaphore, SDK retries with backoff, idempotency key = ticket id + `kb_version` + config. | `pipeline.process_many`, `AnthropicBackend` |
| Regressions | Every prompt/KB/model change runs the eval. `--gate` exits 1 if escalation recall < 100%, any trading-advice request isn't declined, or any hard-rule violation reaches an agent. | `evals/run_eval.py --gate` |
| Monitoring | Per-ticket JSON log → dashboard: queue mix, abstain rate (= KB gap signal), validator block rate, cost, p95 latency, agent "sent as is" rate, edit distance, escalation overrides by specialists. Alerts on drift. | output schema |
| Auto-send (optional, later) | Only for `ready` drafts in low-risk categories, after ≥4 weeks of measured "sent as is" ≥ 95% and 0 violations on real traffic. Off by default. | routing extension |
| More languages / channels | Already language-agnostic: the reply follows the customer's language, and KB facts are quoted from the English source. Add per-locale KB when it exists. | prompts |

## Data flow and auditability

Every output can be reproduced: `config` (model, effort, mode) + `kb_version` + the ticket text. A
disputed reply can be traced to the chunk and the quote that justified each claim. That matters for a
regulated broker, where "why did support say X" is a compliance question.
