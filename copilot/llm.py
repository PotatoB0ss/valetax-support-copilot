"""LLM backends.

`AnthropicBackend` — real calls (Claude via the official SDK, structured JSON outputs, prompt caching).
`MockBackend`     — deterministic, offline; rule-based triage + template drafts from BM25 hits.
                    Lets tests, CI and the demo run without a key. It is NOT what we measure for quality.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field

from . import prompts
from .config import Config, cost_usd
from .guardrails import detect_risks
from .kb import Chunk
from .retrieval import BM25
from .schema import DRAFT_SCHEMA, SINGLE_SCHEMA, TRIAGE_SCHEMA


FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}  # Haiku 5.5 has no server-side fallback


class LLMRefusal(Exception):
    pass


@dataclass
class CallStat:
    step: str
    model: str
    latency_s: float
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    stop_reason: str = ""
    request_id: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class AnthropicBackend:
    def __init__(self, cfg: Config, max_concurrency: int = 8):
        import anthropic

        self.cfg = cfg
        self.client = anthropic.AsyncAnthropic(max_retries=4, timeout=120.0)
        self.sem = asyncio.Semaphore(max_concurrency)

    async def _call(self, step: str, model: str, system: str, user: str, schema: dict, max_tokens: int = 6000,
                    on_text=None) -> tuple[dict, CallStat]:
        """One structured call. With `on_text`, the response is streamed and `on_text(json_so_far)` is called
        on every text delta (used by the web UI to show classification and the draft while it is generated)."""
        cache = {"type": "ephemeral", **({"ttl": self.cfg.cache_ttl} if self.cfg.cache_ttl else {})}
        async with self.sem:
            t0 = time.perf_counter()
            kwargs = dict(
                model=model,
                max_tokens=max_tokens,
                # Stable prefix (rules + KB) is cached; the ticket is the only per-request part.
                system=[{"type": "text", "text": system, "cache_control": cache}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self.cfg.effort, "format": {"type": "json_schema", "schema": schema}},
            )
            if model in FALLBACK_MODELS:
                # Server-side refusal fallback: if a safety classifier declines, the API re-runs the
                # request on Anthropic's recommended fallback model inside the same call.
                api, kwargs = self.client.beta.messages, {**kwargs, "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
            else:
                api = self.client.messages
            if on_text is None:
                resp = await api.create(**kwargs)
            else:
                buf = []
                async with api.stream(**kwargs) as stream:
                    async for ev in stream:
                        if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                            buf.append(ev.delta.text)
                            on_text("".join(buf))
                    resp = await stream.get_final_message()
            dt = time.perf_counter() - t0
        u = resp.usage
        usage = {
            "input_tokens": u.input_tokens or 0,
            "output_tokens": u.output_tokens or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        }
        stat = CallStat(step, model, round(dt, 3), usage, cost_usd(model, usage), resp.stop_reason or "", getattr(resp, "_request_id", "") or "")
        if resp.stop_reason == "refusal":
            raise LLMRefusal(f"{model} refused ({getattr(resp.stop_details, 'category', None)})")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError(f"{model} hit max_tokens in step {step}")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text), stat

    async def single(self, ticket: str, chunks: list[Chunk], model: str, on_text=None) -> tuple[dict, CallStat]:
        return await self._call("single", model, prompts.single_system(chunks), prompts.ticket_message(ticket), SINGLE_SCHEMA, on_text=on_text)

    async def triage(self, ticket: str) -> tuple[dict, CallStat]:
        return await self._call("triage", self.cfg.triage_model, prompts.TRIAGE_SYSTEM, prompts.ticket_message(ticket), TRIAGE_SCHEMA, 3000)

    async def draft(self, ticket: str, triage: dict, chunks: list[Chunk], model: str, on_text=None) -> tuple[dict, CallStat]:
        return await self._call("draft", model, prompts.DRAFT_SYSTEM, prompts.draft_message(ticket, triage, chunks), DRAFT_SCHEMA, on_text=on_text)


# ------------------------------------------------------------------------------------------- mock
_CAT_KEYWORDS = [
    ("withdrawal", r"withdraw|вывод|вывести|retir|saque|sacar|سحب|tarik|rút"),
    ("verification", r"verif|kyc|верифик|документ|document|selfie|passport|паспорт|التحقق"),
    ("deposit", r"deposit|депозит|пополн|fund|depósito|إيداع|setor|nạp"),
    ("account_opening", r"open (an |a )?account|sign up|register|открыть сч|регистрац|abrir (una )?cuenta|account type|islamic|leverage|плечо"),
]
_LANG_SCRIPTS = [("ru", r"[а-яё]"), ("ar", r"[؀-ۿ]"), ("vi", r"[ạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹđ]")]
_LANG_WORDS = [("es", r"\b(hola|cuenta|retiro|depósito|por favor|dinero)\b"), ("pt", r"\b(olá|conta|saque|depósito|dinheiro)\b"), ("id", r"\b(saya|akun|dana|bagaimana|tidak)\b")]


class MockBackend:
    def __init__(self, cfg: Config, chunks: list[Chunk]):
        self.cfg = cfg
        self.bm25 = BM25(chunks)

    @staticmethod
    def _lang(t: str) -> str:
        low = t.lower()
        for code, pat in _LANG_SCRIPTS + _LANG_WORDS:
            if re.search(pat, low):
                return code
        return "en"

    def _triage(self, ticket: str) -> dict:
        low = ticket.lower()
        flags = sorted(detect_risks(ticket))
        cat = "other"
        if "trading_advice_request" in flags:
            cat = "trading"
        for c, pat in _CAT_KEYWORDS:
            if re.search(pat, low):
                cat = c
                break
        neg = bool(flags and set(flags) & {"complaint", "legal_threat", "account_security"}) or bool(re.search(r"!{2,}|angry|terrible|жду|still|до сих пор", low))
        urgency = "critical" if set(flags) & {"account_security", "legal_threat"} else "high" if neg or cat == "withdrawal" else "low"
        return {"language": self._lang(ticket), "category": cat, "urgency": urgency,
                "sentiment": "negative" if neg else "neutral", "risk_flags": flags,
                "summary_en": ticket[:120], "search_query_en": ticket}

    def _draft(self, ticket: str, triage: dict, chunks: list[Chunk]) -> dict:
        if triage["risk_flags"] == ["trading_advice_request"]:
            return {"response_mode": "decline", "draft_reply": "Hello,\n\nWe are not able to provide trading advice, signals or recommendations. Trading decisions are yours to make.\n\nValetax Support",
                    "claims": [], "unanswered_questions": [], "internal_note": "Trading-advice request declined."}
        hits = BM25(chunks).search(triage.get("search_query_en") or ticket, k=1)
        if not hits:
            return {"response_mode": "abstain", "draft_reply": "", "claims": [], "unanswered_questions": [triage["summary_en"]],
                    "internal_note": "No KB match."}
        c = hits[0]
        sentence = re.split(r"(?<=[.!])\s", c.text)[0]
        return {"response_mode": "answer", "draft_reply": f"Hello,\n\n{sentence}\n\nValetax Support",
                "claims": [{"chunk_id": c.id, "quote": sentence}], "unanswered_questions": [], "internal_note": "Mock draft (top BM25 hit)."}

    async def single(self, ticket: str, chunks: list[Chunk], model: str, on_text=None):
        t = self._triage(ticket)
        t.pop("search_query_en")
        return {**t, **self._draft(ticket, {**t, "search_query_en": ticket}, chunks)}, CallStat("single", "mock", 0.0)

    async def triage(self, ticket: str):
        return self._triage(ticket), CallStat("triage", "mock", 0.0)

    async def draft(self, ticket: str, triage: dict, chunks: list[Chunk], model: str, on_text=None):
        return self._draft(ticket, triage, chunks), CallStat("draft", "mock", 0.0)
