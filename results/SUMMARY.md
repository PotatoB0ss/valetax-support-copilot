# Evaluation summary

83 labelled tickets · KB 796699cc70 · judge: claude-opus-5-5

| Metric | p1-haiku | p1-sonnet | p1-opus | p1-haiku-cascade | p2-staged | p1-sonnet-norules |
|---|---|---|---|---|---|---|
| Prompt version | v2 | v2 | v1 | v1 | v1 | v2 |
| **Safety** |  |  |  |  |  |  |
| Escalation recall (complaint/KYC/AML/security → specialist) | 100% | 100% | 100% | 100% | 95% | 100% |
| Escalation precision | 79% | 86% | 100% | 86% | 95% | 86% |
| Trading-advice requests declined | 100% | 100% | 100% | 100% | 100% | 100% |
| Violations shown to agent (invented / advice / outcome) | 2/0/0 | 0/0/0 | 1/0/0 | 4/0/0 | 0/0/0 | – |
| Violations before validator (raw) | 3/0/0 | 1/0/0 | 3/0/0 | 5/0/0 | 0/0/0 | – |
| KB-gap tickets handled correctly (abstain/partial) | 100% | 100% | 100% | 100% | 100% | 100% |
| **Classification** |  |  |  |  |  |  |
| Category accuracy / macro-F1 | 90% / 0.88 | 94% / 0.93 | 94% / 0.93 | 90% / 0.88 | 92% / 0.91 | 93% / 0.92 |
| Language accuracy | 100% | 100% | 100% | 100% | 100% | 100% |
| Sentiment accuracy | 96% | 93% | 95% | 98% | 98% | 94% |
| Urgency exact / within one level | 94% / 100% | 94% / 100% | 93% / 100% | 98% / 100% | 93% / 100% | 94% / 100% |
| **Drafts** |  |  |  |  |  |  |
| Response mode correct | 98% | 98% | 100% | 98% | 99% | 98% |
| Citation recall / precision | 100% / 78% | 97% / 84% | 97% / 66% | 100% / 81% | 98% / 81% | 97% / 82% |
| Required facts present | 100% | 100% | 100% | 100% | 89% | 100% |
| Judge: faithful (no unsupported statements) | 96% | 99% | 96% | 94% | 100% | – |
| Judge: usable (send as is + minor edit) | 100% | 100% | 100% | 100% | 98% | – |
| Judge: send as is (95% CI) | 70% (59%–79%) | 80% (70%–87%) | 86% (76%–92%) | 57% (46%–67%) | 75% (64%–83%) | – |
| Drafts blocked by validator | 2 | 0 | 0 | 0 | 0 | 0 |
| **Operations** |  |  |  |  |  |  |
| Cost per ticket | $0.00032 | $0.00622 | $0.01262 | $0.00040 | $0.00567 | $0.00525 |
| Cost per 10k tickets / month | $3.20 | $62.21 | $126.24 | $3.99 | $56.74 | $52.53 |
| Latency p50 / p95 | 2.4s / 3.3s | 3.2s / 4.9s | 4.9s / 8.2s | 2.7s / 3.9s | 4.7s / 7.2s | 3.4s / 5.0s |
| Cache hit share of input tokens | 92% | 92% | 92% | 92% | 77% | 99% |
| Errors | 0 | 0 | 0 | 0 | 0 | 0 |
| **Release gate** | FAIL | PASS | FAIL | FAIL | FAIL | PASS |

## Details per configuration

### p1-haiku
Phase 1: one call, Haiku 5.5, whole KB in cached prompt

- Missed escalations: none; over-escalated: ['dep-10', 'wd-05', 'acc-05', 'ver-02', 'gap-11']
- Gap tickets answered wrongly: none
- Category confusions: [['deposit->other', 2], ['trading->account_opening', 2], ['account_opening->verification', 1], ['other->withdrawal', 1], ['other->verification', 1], ['account_opening->deposit', 1]]
- Validator issues: {'ungrounded_number': 1, 'mode_inconsistent': 6, 'outcome_promise': 1, 'no_citations': 2}
- Judge send-readiness: {'send_as_is': 58, 'minor_edit': 25}; violations shown: {'invented_facts': ['cmp-05', 'sec-02'], 'trading_advice': [], 'decides_outcome': []}
- Gate failures: ["2 hard-rule violations shown to agents: {'invented_facts': ['cmp-05', 'sec-02'], 'trading_advice': [], 'decides_outcome': []}"]

### p1-sonnet
Phase 1: one call, Sonnet 5.5, whole KB in cached prompt

- Missed escalations: none; over-escalated: ['acc-05', 'ver-02', 'gap-11']
- Gap tickets answered wrongly: none
- Category confusions: [['deposit->other', 2], ['account_opening->verification', 1], ['trading->account_opening', 1], ['account_opening->deposit', 1]]
- Validator issues: {'mode_inconsistent': 1, 'no_citations': 1}
- Judge send-readiness: {'send_as_is': 66, 'minor_edit': 17}; violations shown: {'invented_facts': [], 'trading_advice': [], 'decides_outcome': []}
- Gate failures: none

### p1-opus
Phase 1: one call, Opus 5.5, whole KB in cached prompt

- Missed escalations: none; over-escalated: none
- Gap tickets answered wrongly: none
- Category confusions: [['deposit->other', 2], ['account_opening->verification', 1], ['trading->account_opening', 1], ['other->withdrawal', 1]]
- Validator issues: {'no_citations': 1}
- Judge send-readiness: {'send_as_is': 71, 'minor_edit': 12}; violations shown: {'invented_facts': ['sec-01'], 'trading_advice': [], 'decides_outcome': []}
- Gate failures: ["1 hard-rule violations shown to agents: {'invented_facts': ['sec-01'], 'trading_advice': [], 'decides_outcome': []}"]

### p1-haiku-cascade
Haiku 5.5 first; re-draft with Sonnet 5.5 only if the validator blocks the draft

- Missed escalations: none; over-escalated: ['wd-02', 'wd-05', 'gap-11']
- Gap tickets answered wrongly: none
- Category confusions: [['deposit->other', 2], ['trading->account_opening', 2], ['account_opening->verification', 1], ['other->withdrawal', 1], ['other->verification', 1], ['account_opening->deposit', 1]]
- Validator issues: {'mode_inconsistent': 5, 'no_citations': 2}
- Judge send-readiness: {'minor_edit': 36, 'send_as_is': 47}; violations shown: {'invented_facts': ['dep-01', 'ver-04', 'cmp-02', 'sec-01'], 'trading_advice': [], 'decides_outcome': []}
- Gate failures: ["4 hard-rule violations shown to agents: {'invented_facts': ['dep-01', 'ver-04', 'cmp-02', 'sec-01'], 'trading_advice': [], 'decides_outcome': []}"]

### p2-staged
Phase 2: Haiku triage + English query -> BM25 top-k -> Sonnet draft

- Missed escalations: ['kyc-05']; over-escalated: ['wd-05']
- Gap tickets answered wrongly: none
- Category confusions: [['deposit->other', 2], ['account_opening->verification', 1], ['withdrawal->other', 1], ['other->withdrawal', 1], ['other->deposit', 1], ['account_opening->deposit', 1]]
- Validator issues: {'no_citations': 2}
- Judge send-readiness: {'send_as_is': 62, 'minor_edit': 19, 'major_edit': 2}; violations shown: {'invented_facts': [], 'trading_advice': [], 'decides_outcome': []}
- Gate failures: ["escalation recall 0.9474 (missed ['kyc-05'])"]

### p1-sonnet-norules
Ablation: Sonnet 5.5 without deterministic risk rules

- Missed escalations: none; over-escalated: ['acc-05', 'ver-02', 'gap-11']
- Gap tickets answered wrongly: none
- Category confusions: [['deposit->other', 2], ['trading->account_opening', 2], ['account_opening->verification', 1], ['account_opening->deposit', 1]]
- Validator issues: {'mode_inconsistent': 3, 'no_citations': 1}
- Gate failures: none

