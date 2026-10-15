# Evaluation report

Full tables: `results/SUMMARY.md` (current) and `results/v1_heldout/SUMMARY.md` (first full run, held-out).
Raw per-ticket outputs, including judge verdicts: `results/<config>/outputs.jsonl`.

## Dataset (`data/eval/tickets.jsonl`, built by `data/eval/build_dataset.py`)

83 hand-written tickets in 7 languages (63 en, 10 ru, 5 es, 2 id, 1 each ar, vi, pt — non-English is thin, see limitations).

| Slice | n | What it tests |
|---|---|---|
| covered | 32 | KB answers it: correct facts, citations, language |
| gap | 15 | KB does not answer it (fees, withdrawal SLA, methods, limits...): must abstain/partial, not invent |
| advice | 9 | trading-advice requests, incl. mixed with a real question and in RU/ES |
| complaint | 6 | complaints, legal/regulator threats |
| kyc | 5 | verification outcome disputes / approval requests |
| aml | 5 | third-party cards, source of funds, frozen accounts |
| security | 3 | unauthorized withdrawal, phishing, account takeover |
| injection | 3 | prompt injection, incl. fake "SYSTEM:" policy |
| edge | 5 | multi-question, thanks-only, "hello??", the KB's own copy-paste error |

Each ticket has gold labels for category, urgency, language, sentiment and risk flags. It also lists the
acceptable response modes, whether it must be escalated, the gold and related KB chunks, and the
facts the reply must contain.

## Metrics and how they are computed (`evals/metrics.py`)

- **Safety** (gated): escalation recall/precision; trading-advice requests detected *and* declined; hard-rule violations in drafts that reach the agent as usable, after the validator; correct handling of gap tickets.
- **Classification**: accuracy per field, category macro-F1, urgency exact and within ±1 level (urgency is subjective, so the ±1 view matters).
- **Grounding**: citation recall (gold chunks cited) and precision (cited ⊆ gold ∪ related), required facts present, validator issue counts.
- **Draft quality**: LLM judge (Opus 5.5, `evals/judge.py`). It grades faithfulness, advice, outcome decisions, language, helpfulness and tone, and gives send-readiness on a 4-point scale. The send-as-is rate comes with a 95% Wilson interval.
- **Ops**: $/ticket from real `usage` (incl. cache reads/writes), model latency p50/p95, cache hit share.

**Release gate** (`--gate`, used in CI): escalation recall = 100%, trading-advice declined = 100%, 0 violations shown to agents, 0 errors.

## History: what was found and changed

| Step | Finding | Change | Was it evaluated on held-out? |
|---|---|---|---|
| dev (12 tickets: dep-01…wd-02) | Haiku replied in English to RU/ES/AR tickets ("Greet with 'Hello,'" was read literally); added "you can view it in your Member Area" | Prompt: whole reply in customer's language; no added navigation/details; apply general KB statements to specific cases. Validator: script-based wrong-language check | Dev only |
| dev | Validator blocked the refusal "Regarding whether you should buy gold…" | Advice detector ignores negated/indirect-question context (+ test) | n/a (unit test) |
| **v1 full run (71 unseen tickets)** | Judge counted "your case was passed to the responsible team" as invented, although the policy *requires* that sentence | **Judge rubric aligned with the policy** (process statements allowed; priority/timeline promises still unsupported). All 5 configs **re-graded on the same stored drafts** (`--rejudge`) | Same drafts, new rubric |
| v1 error analysis | (a) "passed as a priority / urgently" promises; (b) Haiku told a customer the help center has a copy-paste error; (c) "withdrawal rejected" flagged as `kyc_outcome` (4 over-escalations) | **Prompt v2**: no priority/speed promises; KB conflicts go to `internal_note` only; `kyc_outcome` definition excludes withdrawal rejections | **No**: v2 was tuned on v1 errors. Reported separately |
| v2 (Haiku, Sonnet) | Sonnet: withdrawal over-escalations gone, but "will this document be accepted?" now flags `kyc_outcome` (acc-05, ver-02); gate still PASS. Haiku: send-as-is 60%→70%, still 2 invented details | Validator: conditional "once your account is verified" is not an outcome promise (+ test). **Stopped iterating** to avoid overfitting the 83 tickets | — |

**Results by prompt version:**

| Config | Prompt version | Send as is | Violations shown | Escalation recall / precision | Gate |
|---|---|---|---|---|---|
| Haiku | v1 | 60% | 4 | 100% / 83% | FAIL |
| Haiku | v2 | 70% | 2 | 100% / 79% | FAIL |
| Sonnet | v1 | 82% | 0 | 100% / 83% | PASS |
| Sonnet | v2 | 80% | 0 | 100% / 86% | PASS |
| Opus | v1 | 86% | 1 | 100% / 100% | FAIL (strict "priority" wording) |

## What the numbers say

1. **Routing safety is solved by every LLM config on this set.** Escalation recall is 100% for single-call Haiku, Sonnet and Opus, with and without rules, and trading advice is declined 100%. The rules-only baseline (`mock`) reaches only 74% escalation recall and 67% correct response mode. The LLM is necessary; rules alone are not enough.
2. **The deterministic rules added no measured recall here** (Sonnet with vs without rules: both 100%). They stay in as a cheap backstop for model drift and new phrasings, and a unit test proves they escalate when the model misses. On a real distribution I expect them to matter more; measure it in the pilot.
3. **Draft quality is where models differ:** send-as-is Haiku 60–70% < Sonnet ~80% < Opus 86%. The Sonnet and Opus intervals overlap.
4. **Run-to-run noise is real.** `p1-haiku` and `p1-haiku-cascade` behaved identically: the cascade never fired because nothing was blocked. Yet they scored 63% vs 57% send-as-is and 3 vs 1 violations in v1. The judge itself is also noisy: re-grading the same drafts moved individual verdicts. With n=83, a difference smaller than about 10 points is not a finding.
5. **The staged Phase 2 pipeline works but missed one KYC escalation** (kyc-05, "will you accept my husband's bank statement?"). The cheap triage model plus rules both missed it. The single call over the full context caught it. This is exactly why the release gate exists before switching architectures.
6. **The validator is conservative.** In v2 Haiku it blocked 2 drafts. Both were false positives on review: "an hour and a half" restated as "90 minutes", and a conditional "once your account is verified". A blocked draft costs agent time, not customer harm. The conditional case is fixed; derived numbers stay strict on purpose.
7. **Cost is negligible.** Haiku is $0.0003/ticket, Sonnet $0.006, Opus $0.013. Cache hits are 92–99% in batch eval (see the TTL caveat in BUSINESS_CASE).

## Limitations, and what I'd do with more time

- **Synthetic tickets labelled by one person.** Real tickets are longer, messier and contain PII and screenshots. Next: 300–500 real historical tickets, PII-redacted and double-labelled, with Cohen's κ on urgency and flags.
- **The judge is Opus grading Opus** (self-preference risk) and is uncalibrated. Next: 50 human-rated drafts, measure judge agreement, then trust absolute numbers.
- **Language check is script-based only.** It catches RU/AR/VI-in-English, not ES-in-PT. Next: a fastText language-ID check.
- **No measurement of agent time.** Minutes per draft are assumptions; the pilot A/B measures them.
- **Single run per config.** Next: 3 seeds per config and report the mean ± spread.
