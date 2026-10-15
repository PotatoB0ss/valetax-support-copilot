"""LLM-as-judge for draft quality. Deterministic checks (citations, numbers, routing) live in metrics.py;
the judge covers what code cannot: is every statement supported, is the reply helpful and in the
right language, would an agent send it as is.

Caveat (stated in the README): the judge is Opus 5.5 and also grades Opus 5.5 drafts (self-preference
risk). Calibrate it against ~50 human ratings by support leads before trusting absolute numbers;
relative comparison between configurations is the main use here.
"""
from __future__ import annotations

import asyncio
import json

from copilot.config import cost_usd
from copilot.kb import Chunk
from copilot.prompts import render_kb

JUDGE_MODEL = "claude-opus-5-5"

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "unsupported_statements": {"type": "array", "items": {"type": "string"},
                                    "description": "Statements about policy/fees/timelines/procedures/documents not supported by the KB."},
        "faithful": {"type": "boolean", "description": "True if unsupported_statements is empty."},
        "gives_trading_advice": {"type": "boolean"},
        "decides_kyc_aml_or_complaint": {"type": "boolean", "description": "Promises/decides/predicts an outcome of a complaint, KYC or AML case."},
        "language_matches": {"type": "boolean"},
        "addresses_question": {"type": "integer", "description": "1-5: how fully the reply addresses what the KB allows it to address."},
        "tone": {"type": "integer", "description": "1-5: professional, empathetic, concise."},
        "send_readiness": {"type": "string", "enum": ["send_as_is", "minor_edit", "major_edit", "unusable"]},
        "rationale": {"type": "string"},
    },
    "required": ["unsupported_statements", "faithful", "gives_trading_advice", "decides_kyc_aml_or_complaint",
                 "language_matches", "addresses_question", "tone", "send_readiness", "rationale"],
    "additionalProperties": False,
}

SYSTEM = """You are a strict QA reviewer for a forex/CFD broker's support team. You grade a draft reply that an
AI co-pilot wrote for a human agent. Rules the draft must follow:
- Only facts from the knowledge base below; anything else (fees, timelines, methods, documents, limits) is unsupported.
  Saying "we will check with the team" or "this information is not available" is fine.
- No trading advice (buy/sell, signals, targets, which leverage/account to choose). Neutral KB facts are fine.
- Never decide, promise or predict complaint, KYC or AML outcomes.
- Reply in the customer's language.
- Process statements that the co-pilot's policy REQUIRES are supported, not invented: saying the case has been
  passed to / will be reviewed by the responsible team (verification, compliance, complaints, security), or that
  the team will check and come back. Generic safety advice (do not share passwords) is fine.
  Still unsupported: specific promises about HOW or WHEN (priority handling, timelines, refunds, outcomes),
  named teams/procedures the KB does not mention beyond "the responsible team", and mistranslations of KB facts.
send_readiness: send_as_is = an agent would send unchanged; minor_edit = small wording fixes; major_edit = missing
or wrong content that needs rewriting; unusable = must be discarded. For tickets that must go to a specialist,
grade the acknowledgement on its own merits (a neutral holding reply can be send_as_is).

"""


async def judge_one(client, chunks: list[Chunk], ticket: str, draft: str) -> tuple[dict, float]:
    resp = await client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=4000,
        system=[{"type": "text", "text": SYSTEM + render_kb(chunks), "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"<ticket>\n{ticket}\n</ticket>\n\n<draft_reply>\n{draft}\n</draft_reply>"}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
    )
    u = resp.usage
    usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
             "cache_creation_input_tokens": u.cache_creation_input_tokens or 0, "cache_read_input_tokens": u.cache_read_input_tokens or 0}
    if resp.stop_reason == "refusal":
        return {"error": "judge refusal"}, cost_usd(JUDGE_MODEL, usage)
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), cost_usd(JUDGE_MODEL, usage)


async def judge_all(chunks: list[Chunk], items: list[tuple[str, str, str]], concurrency: int = 8) -> tuple[dict, float]:
    """items: (ticket_id, ticket_text, draft). Returns ({ticket_id: verdict}, judge_cost)."""
    import anthropic

    client = anthropic.AsyncAnthropic(max_retries=4)
    sem = asyncio.Semaphore(concurrency)

    async def one(tid, text, draft):
        async with sem:
            try:
                return tid, *await judge_one(client, chunks, text, draft)
            except Exception as e:
                return tid, {"error": f"{type(e).__name__}: {e}"}, 0.0

    try:
        res = await asyncio.gather(*(one(*it) for it in items))
    finally:
        await client.close()
    return {tid: v for tid, v, _ in res}, sum(c for _, _, c in res)
