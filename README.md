# Support-ticket co-pilot for a retail forex/CFD broker

For every incoming ticket the co-pilot **classifies** it (category, urgency, language, sentiment, risk flags), **drafts a
reply grounded in the Valetax help pages with citations** (or abstains when the KB doesn't cover it), and **routes** it
to the right human: an agent for one-click review, or a specialist queue (complaints, compliance, security) for
anything the co-pilot must never decide.

**→ One-page answer to "is it worth it, and with which configuration": [BUSINESS_CASE.md](BUSINESS_CASE.md)**
(yes: `p1-sonnet`, ≈3 FTE saved, ≈+$4.3k/month net at 10k tickets, ≈3-month payback).

| Doc | What's in it |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Phase 1 (ship) vs Phase 2 (scale), defence-in-depth for the hard rules, what's stubbed and what the real version does |
| [docs/EVAL_REPORT.md](docs/EVAL_REPORT.md) | Dataset, metrics, v1 → v2 history, error analysis, noise, limitations |
| [results/SUMMARY.md](results/SUMMARY.md) | Side-by-side metrics for 6 configurations (+ rules-only baseline) |
| [docs/KB_AUDIT.md](docs/KB_AUDIT.md) | Gaps, duplicates and contradictions in the 4 KB pages, and how the co-pilot handles each |
| [results/scale_sim.md](results/scale_sim.md) | Phase 2 simulation: retrieval recall and cost as the KB grows to 20k chunks |

## Brief → where it is done

| Requirement in the brief | Where |
|---|---|
| Classify: category, urgency, language, sentiment | `copilot/schema.py`, rubric in `copilot/prompts.py`; measured in `results/SUMMARY.md` |
| Draft grounded in the KB with citations, or abstain | `claims[{chunk_id, quote}]` + validator (`copilot/guardrails.py`); `response_mode = abstain` |
| Route to a human reviewer whenever required | `copilot/routing.py` (agent review / manual / complaints / compliance / security) |
| Never give trading advice | prompt rule + multilingual rules + draft detector; 100% declined in eval |
| Never decide complaint/KYC/AML outcomes | specialist queues + outcome-promise detector; 100% escalation recall |
| Never invent policy, fees, timelines | verbatim-quote + grounded-number checks; judge faithfulness; release gate |
| KB = 4 Valetax pages, as they are | `data/kb_raw/` snapshots, `docs/KB_AUDIT.md` (gaps, overlaps, inconsistencies) |
| Phase 1 ship ASAP / Phase 2 scale (10k/month, growing KB/SOPs) | `docs/ARCHITECTURE.md`, `p2-staged` config, `results/scale_sim.md` |
| Measure it | `evals/` (83 labelled tickets, 6 configs, judge, CI gate) |
| Business case on one page: worth it, which configuration | [BUSINESS_CASE.md](BUSINESS_CASE.md) |
| Python; any LLM provider | Python 3.12; Claude (Haiku / Sonnet / Opus 5.5) via the official `anthropic` SDK, structured outputs, prompt caching |
| Built with an agentic coding tool | Built with Claude Code |
| Minimal CLI or simple web page | `python -m copilot triage/batch` and `python -m copilot serve` (password-protected web UI) |
| Mocks/stubs explained | [ARCHITECTURE.md → what is stubbed](docs/ARCHITECTURE.md#phase-1-what-ships-in-week-1) |

## Quick start

```bash
uv sync                                          # Python 3.12, deps: anthropic, beautifulsoup4
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env        # or export it
echo 'COPILOT_PASSWORD=choose-a-password' >> .env # web UI password (if unset, one is generated and printed)

uv run python -m copilot triage "Какой минимальный депозит? И стоит ли сейчас покупать золото?"
uv run python -m copilot --config p1-haiku triage "My withdrawal is pending for 6 days, you are scammers"
uv run python -m copilot batch data/eval/tickets.jsonl -o out.jsonl
uv run python -m copilot serve                   # web UI on http://127.0.0.1:8000 (password login, Opus by default)
uv run python -m copilot configs                 # list configurations

uv run pytest -q                                 # 32 unit tests, offline
uv run python -m evals.run_eval --configs mock   # offline eval (rules-only baseline), no key needed
uv run python -m evals.run_eval --configs p1-sonnet,p1-haiku --judge   # real eval + LLM judge (~$1.5)
uv run python -m evals.run_eval --configs p1-sonnet --judge --gate     # CI release gate (exit 1 on failure)
uv run python -m business_case.model             # recompute the business case from results + assumptions
uv run python -m evals.scale_sim                 # Phase 2 KB-growth simulation (offline)
```

`python -m copilot` is used instead of the `copilot` entry point because, in some macOS setups, `.pth` files in
`.venv` get the `hidden` flag and Python skips them. On Linux, `uv run copilot …` works too.

Example output (real run, `p1-sonnet`):

```
Category: deposit   Urgency: low   Language: ru   Sentiment: neutral
Risk flags: trading_advice_request (llm)
Route: agent_review  priority P4  draft: needs_edit  mode: partial
  · trading-advice request: draft declines it; agent must not add advice
Draft reply:
  Здравствуйте,
  Минимальный депозит начинается от 8 USD, в зависимости от типа счёта.
  К сожалению, мы не можем давать торговых рекомендаций, в том числе подсказывать, стоит ли покупать золото…
  Valetax Support
Sources:
  [faq/minimum-deposit-amount] What is the minimum deposit amount? — https://valetax.com/how-to-deposit/
cost $0.00478 · 3.7s · calls: claude-sonnet-5-5
```

## How it works

```
ticket ─┬─ rules (multilingual regex: advice / complaint / KYC / AML / security / legal / injection) ─┐
        └─ Claude, 1 call, structured JSON: classification + flags + draft + claims[{chunk_id, quote}]  │
                     (system prompt = rules + whole KB, prompt-cached)                                  │
           ─▶ validator: citation exists · quote is verbatim in chunk · every number grounded ·        │
                         no advice phrasing · no outcome promises · reply in customer's script          │
           ─▶ router (deterministic): flags ∪ rules → specialist queue | blocked/abstain → agent_manual │
                                      | else agent_review (ready / needs_edit) ◀──────────────────────┘
```

| Module | Role |
|---|---|
| `copilot/kb.py` | HTML snapshots → 24 citable chunks; duplicate FAQ stored once with both URLs; content hashes + `kb_version` |
| `copilot/prompts.py` | Hard rules, classification rubric, drafting rules (stable text → cacheable) |
| `copilot/schema.py` | JSON schemas enforced by structured outputs |
| `copilot/llm.py` | Claude backend (async, caching, refusal fallback on Sonnet/Opus) + offline mock |
| `copilot/guardrails.py` | Pre-LLM risk rules and post-LLM draft validator |
| `copilot/routing.py` | Queue / priority / draft status, readable by Compliance |
| `copilot/pipeline.py` | Phase 1 single call, Phase 2 staged (triage → BM25 → draft), optional cascade |
| `copilot/retrieval.py` | BM25 (Phase 2) |
| `evals/` | Eval runner, metrics, LLM judge, release gate, KB-growth simulation |
| `business_case/` | Assumptions (each sourced) + calculator → `RESULTS.md` |

## Key decisions (the short version for the call)

1. **Co-pilot, not autopilot.** Nothing is auto-sent in Phase 1. Every ticket gets a human. Routing decides *which* human, and whether they get a ready draft.
2. **The LLM proposes, code decides.** Routing, validation and the release gate are deterministic. Every hard rule has ≥2 independent layers (prompt + code + process; table in ARCHITECTURE).
3. **Grounding is checkable, not trusted.** The model must back every factual sentence with `claims[{chunk_id, quote}]`. Code verifies that each quote is in the cited chunk and that every number in the reply appears in a cited chunk or in the ticket.
4. **Whole KB in the prompt for Phase 1.** With 4 pages (~1.8k tokens), retrieval adds risk and no value. Prompt caching makes it cheap. The simulation shows where that stops being true (~200 chunks).
5. **Escalation flags are separate from category.** "My withdrawal is late, you're scammers" is category `withdrawal` with flag `complaint`. Topic stats and safety routing don't fight each other.
6. **Model choice by measurement.** Six configs on the same 83 tickets, with a judge and a release gate. Cost turned out to be <1% of value, so the decision is quality and safety, not price.
7. **The KB is used as is.** Contradictions are not "fixed" silently. The prompt says to quote precisely, prefer the conservative statement and note conflicts for the agent. The audit doubles as a content backlog.

## Results at a glance (83 tickets, details in [results/SUMMARY.md](results/SUMMARY.md))

| | rules only | Haiku 5.5 | **Sonnet 5.5** | Opus 5.5 | staged (P2) |
|---|---|---|---|---|---|
| Escalation recall (complaint/KYC/AML/security) | 74% | 100% | **100%** | 100% | 95% |
| Trading-advice requests declined | 60% | 100% | **100%** | 100% | 100% |
| Hard-rule violations shown to agents | – | 2 | **0** | 1 | 0 |
| Category accuracy | 75% | 90% | **94%** | 94% | 92% |
| Drafts sendable as is (judge) | – | 70% | **80%** | 86% | 75% |
| $ per 10k tickets | 0 | $3 | **$62** | $126 | $57 |
| Model latency p50 | – | 2.4s | **3.3s** | 4.9s | 4.7s |
| Release gate | FAIL | FAIL | **PASS** | FAIL | FAIL |

## What is mocked, and what I'd do next

Mocked or stubbed: the helpdesk integration (CLI and web page instead of a Zendesk/Freshdesk sidebar app), real tickets
(synthetic labelled set), PII redaction, monitoring dashboards, and human calibration of the judge. Each item and its
real version is listed in [ARCHITECTURE.md](docs/ARCHITECTURE.md#phase-1-what-ships-in-week-1). Next steps, in order:
a pilot (shadow → A/B) with real ticket evals; publishing the fee and withdrawal-SLA content (largest gap); a
judge calibrated on human ratings; a hybrid multilingual retriever when the KB grows.

## How this was built

Built with Claude Code as the coding agent. The Valetax pages were snapshotted on 2026-10-15 (`data/kb_raw/`).
The eval and judge runs cost about $10 of API usage in total. Prompt iteration history and every judge-rubric
change are disclosed in [docs/EVAL_REPORT.md](docs/EVAL_REPORT.md).
