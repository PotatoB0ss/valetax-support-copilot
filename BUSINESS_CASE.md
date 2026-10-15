# Business case: is the co-pilot worth running at 10,000 tickets/month, and in which configuration?

**Answer: yes. Run `p1-sonnet` in Phase 1:** one Claude Sonnet 5.5 call per ticket, the whole KB in a cached
prompt, deterministic rules, a validator and routing. In the base case it saves about **470 agent-hours a month
(≈3 FTE)** for **≈$2.8k/month** all-in. That is **≈+$4.3k/month net** and a **≈3-month payback**. It stays
positive down to an agent cost of **≈$6/hour** or a volume of **≈3,900 tickets/month**. Model spend is
**<1% of the value**, so the configuration is chosen on safety and quality, not on token price.

## The numbers (base case: 10k tickets/month, agent $15/h fully loaded, 6 min baseline handling time)

| | Haiku 5.5 | **Sonnet 5.5** | Opus 5.5 | Phase 2 staged (Haiku triage → Sonnet) |
|---|---|---|---|---|
| Release gate (safety, see below) | ❌ invents details in 2–4 of 83 drafts | ✅ **passed in both runs** | ❌ 1 of 83 (v1) | ❌ missed 1 KYC escalation |
| Drafts an agent would send unchanged (judge, 95% CI) | 70% (59–79%) | **80% (70–87%)** | 86% (76–92%) | 75% (64–83%) |
| Agent minutes saved per ticket | 2.8 | **2.8** | 3.0 | 2.9 |
| Hours saved / month (FTE) | 470 (2.9) | **474 (3.0)** | 505 (3.2) | 491 (3.1) |
| LLM cost / month (measured $/ticket × 10k) | $3 | **$62** | $126 | $57 |
| Total cost / month (LLM + eval + hosting + 0.15 FTE eng + KB upkeep) | $2,756 | **$2,817** | $2,883 | $2,811 |
| Value / month (hours × $15) | $7,056 | **$7,104** | $7,576 | $7,360 |
| **Net / month** | $4,300 | **$4,288** | $4,693 | $4,549 |
| Payback of ~$12k build | 2.8 mo | **2.8 mo** | 2.6 mo | 2.6 mo |
| Latency p50 / p95 (model time) | 2.4 / 3.3 s | **3.3 / 4.9 s** | 4.9 / 8.2 s | 4.7 / 7.2 s |

Sensitivity (Sonnet, net $/month): agent **$8/h → +$1.0k**, **$15/h → +$4.3k**, **$30/h → +$11.4k**.
Volume **5k → +$0.8k**, **20k → +$11.3k**, **50k → +$32.5k**, **100k → +$67.7k**.
The fixed cost is mostly people (maintenance, KB curation), so the case improves with volume much faster than linearly.

## Why Sonnet, not the cheapest or the best-scoring

- **Haiku is 20× cheaper, but that saves only ~$60/month.** It invented small details in 2–4 drafts per 83 (a mistranslated KB fact, "Valetax will never ask for your CVV", an unrequested list of documents). "Never invent policy" is a hard rule, and $60/month does not buy that risk. Haiku is good enough at *classification* (category 90–92%, 100% escalation recall), so it becomes the **triage model in Phase 2**.
- **Opus is +$400/month better on paper,** but the difference is inside the confidence interval (n=83). It is 1.5× slower and failed the strict gate once. **A/B it against Sonnet in the pilot**, measured on the real "sent as is" rate. Switching is a one-line config change.
- **The Phase 2 staged pipeline is not needed yet.** With 4 pages, the whole-KB prompt is cheaper and cannot miss a chunk (`results/scale_sim.md`). Staged becomes worth it when the KB passes roughly 200 chunks. It also missed one KYC escalation that the single call caught. That is a recall regression the gate exists to stop.

## What is measured vs assumed (and how the pilot closes the gap)

**Measured** on 83 labelled tickets in 7 languages (`results/SUMMARY.md`): routing safety (100% of complaint, KYC, AML and security tickets reach a specialist; 100% of trading-advice requests are declined), classification, grounding, draft quality (LLM judge), $/ticket and latency.
**Assumed** (`business_case/assumptions.json`, every number sourced): baseline 6 min handling time; 1.5 / 2.5 / 5 min to send a draft that needs no / minor / major edits; the inbox mix (17% KB gaps, 18% specialist tickets); $15/h agent cost; 0.15 FTE engineering.
The biggest uncertainty is minutes per draft, not model cost. **Pilot design:** 2 weeks in shadow mode (drafts as internal notes only), then 4 weeks A/B with half of the agents. Go/no-go:

- handling time −30% or better on co-pilot tickets;
- ≥60% of drafts sent with minor or no edits;
- 0 hard-rule violations in a weekly compliance sample of 100 replies;
- escalation recall 100% in that sample.

**Kill switch:** any violation reaching a customer pauses drafting and falls back to triage-only, which still saves ~0.5 min/ticket.

## Levers that matter more than the model

1. **Close KB gaps.** 17% of the assumed inbox asks things the 4 pages don't answer: withdrawal times, fees, methods (`docs/KB_AUDIT.md`). Those tickets get no draft today. Publishing a fee + SLA table turns them into ~2-minute tickets: roughly **+100 h/month (≈+$1.5k)**, more than any model upgrade.
2. **Agent adoption.** Value scales with the "sent as is" rate. Track agent edit distance weekly.
3. **Prompt-cache TTL.** At about 14 tickets/hour, a 5-minute cache often expires between tickets. Measured cost assumes warm caches. With no caching at all, Sonnet would cost ~$150/month instead of $62, which does not change the decision. The 1-hour TTL keeps the cache warm.

*Generated figures: `business_case/RESULTS.md` (`uv run python -m business_case.model`). Eval: `results/SUMMARY.md`. v2 prompt for Haiku/Sonnet, v1 for others; see `docs/EVAL_REPORT.md`.*
