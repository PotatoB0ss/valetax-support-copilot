# Phase 2 simulation: KB growth

27 English eval tickets with gold chunks; KB padded with confusable synthetic SOP chunks. Cost = Sonnet 5.5 input only; 'full, cached' assumes the KB prefix is a cache hit (0.1x), retrieval prompts vary per ticket so are uncached.

| KB chunks | KB tokens | recall@3 | recall@6 | recall@12 | full KB $/ticket (cached) | top-6 $/ticket | fits 1M context? |
|---|---|---|---|---|---|---|---|
| 24 | 1,796 | 80% | 88% | 96% | $0.0010 | $0.0051 | yes |
| 224 | 36,004 | 75% | 88% | 88% | $0.0078 | $0.0051 | yes |
| 1,024 | 174,466 | 70% | 88% | 88% | $0.0355 | $0.0051 | yes |
| 5,024 | 868,470 | 70% | 88% | 88% | $0.1743 | $0.0051 | yes |
| 20,024 | 3,473,895 | 63% | 80% | 88% | $0.6954 | $0.0051 | no |

Reading: with today's 24 chunks, stuffing the whole KB is both cheaper (cache) and risk-free (recall 100% by construction) -> Phase 1 choice.
As SOPs grow into the thousands of chunks, the cached full prompt grows linearly in cost and latency and eventually stops fitting, while lexical recall drops on confusable content -> Phase 2 switches to triage + retrieval, and recall@k becomes a gated eval metric. Upgrade path for recall: hybrid BM25 + multilingual embeddings, metadata filters (category/region), and a reranker.
