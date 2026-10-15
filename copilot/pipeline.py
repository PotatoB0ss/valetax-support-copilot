"""The co-pilot pipeline: ticket -> classification + grounded draft + routing decision.

Phase 1 (mode="single"):  rules ─┐
                          ticket ─┴─> 1 LLM call (whole KB, cached) ─> validate ─> route
Phase 2 (mode="staged"):  ticket ─> triage (cheap model, + English query) ─> BM25 top-k ─> draft (model) ─> validate ─> route
Optional cascade: if validation blocks the draft, re-draft once with a stronger model.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .config import Config
from .guardrails import detect_risks, validate_draft
from .kb import Chunk, kb_version, load_chunks
from .prompts import PROMPT_VERSION
from .llm import AnthropicBackend, LLMRefusal, MockBackend
from .retrieval import BM25
from .routing import route

TRIAGE_KEYS = ("language", "category", "urgency", "sentiment")


class Copilot:
    def __init__(self, cfg: Config, chunks: list[Chunk] | None = None, max_concurrency: int = 8):
        self.cfg = cfg
        self.chunks = chunks or load_chunks()
        self.kb_version = kb_version(self.chunks)
        self.bm25 = BM25(self.chunks)
        self.by_id = {c.id: c for c in self.chunks}
        self.backend = MockBackend(cfg, self.chunks) if cfg.backend == "mock" else AnthropicBackend(cfg, max_concurrency)

    async def _generate(self, ticket: str, model: str) -> tuple[dict, list[Chunk], list]:
        """Returns (merged triage+draft output, chunks the model saw, call stats)."""
        if self.cfg.mode == "single":
            out, stat = await self.backend.single(ticket, self.chunks, model)
            return out, self.chunks, [stat]
        tri, s1 = await self.backend.triage(ticket)
        provided = self.bm25.search(tri.get("search_query_en") or ticket, k=self.cfg.top_k) if self.cfg.retrieval == "bm25" else self.chunks
        dr, s2 = await self.backend.draft(ticket, tri, provided, model)
        return {**tri, **dr}, provided, [s1, s2]

    async def process(self, ticket: str, ticket_id: str = "") -> dict[str, Any]:
        t0 = time.perf_counter()
        rule_hits = detect_risks(ticket) if self.cfg.rules else {}
        calls, error, out, provided, cascaded = [], None, {}, self.chunks, False
        try:
            out, provided, calls = await self._generate(ticket, self.cfg.model)
        except LLMRefusal as e:
            error = str(e)
        except Exception as e:  # network / schema / max_tokens: never lose the ticket, route to a human
            error = f"{type(e).__name__}: {e}"

        llm_flags = set(out.get("risk_flags") or [])
        flags = llm_flags | set(rule_hits)
        issues = [i.as_dict() for i in validate_draft(out, ticket, provided, flags)] if out else []

        if self.cfg.cascade_model and (error or any(i["severity"] == "block" for i in issues)):
            try:
                out2, provided2, calls2 = await self._generate(ticket, self.cfg.cascade_model)
                calls += calls2
                llm_flags = set(out2.get("risk_flags") or [])
                flags = llm_flags | set(rule_hits)
                out, provided, error, cascaded = out2, provided2, None, True
                issues = [i.as_dict() for i in validate_draft(out, ticket, provided, flags)]
            except Exception as e:
                error = error or f"{type(e).__name__}: {e}"

        cited_ids = list(dict.fromkeys(c["chunk_id"] for c in out.get("claims") or [] if c.get("chunk_id") in self.by_id))
        routing = route(flags, out.get("urgency", "high"), out.get("response_mode"), issues, error)
        return {
            "ticket_id": ticket_id,
            "config": self.cfg.name,
            "kb_version": self.kb_version,
            "prompt_version": PROMPT_VERSION,
            "classification": {k: out.get(k) for k in TRIAGE_KEYS},
            "risk_flags": sorted(flags),
            "risk_flag_sources": {f: [s for s, on in (("llm", f in llm_flags), ("rules", f in rule_hits)) if on] for f in sorted(flags)},
            "summary_en": out.get("summary_en", ""),
            "response_mode": out.get("response_mode"),
            "draft_reply": out.get("draft_reply", ""),
            "citations": [{"chunk_id": i, "title": self.by_id[i].title, "url": self.by_id[i].urls[0], "also_on": self.by_id[i].urls[1:]} for i in cited_ids],
            "claims": out.get("claims", []),
            "unanswered_questions": out.get("unanswered_questions", []),
            "internal_note": out.get("internal_note", ""),
            "retrieved": [c.id for c in provided] if self.cfg.mode == "staged" else "full-kb",
            "issues": issues,
            "routing": routing,
            "error": error,
            "cascaded": cascaded,
            "usage": {
                "calls": [c.as_dict() for c in calls],
                "cost_usd": round(sum(c.cost_usd for c in calls), 6),
                "latency_s": round(sum(c.latency_s for c in calls), 3),  # model time (what a ticket costs in seconds)
                "wall_s": round(time.perf_counter() - t0, 3),             # incl. queueing behind the concurrency limit
            },
        }

    async def process_many(self, tickets: list[dict]) -> list[dict]:
        try:
            return await asyncio.gather(*(self.process(t["text"], t.get("id", "")) for t in tickets))
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        client = getattr(self.backend, "client", None)
        if client is not None:
            await client.close()
