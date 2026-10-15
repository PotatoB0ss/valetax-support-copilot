"""Output contracts. The LLM is forced (structured outputs) to return exactly these shapes,
so downstream routing/validation is plain code, never string parsing."""
from __future__ import annotations

CATEGORIES = ["deposit", "withdrawal", "account_opening", "verification", "trading", "other"]
URGENCY = ["low", "medium", "high", "critical"]
SENTIMENT = ["positive", "neutral", "negative"]
RISK_FLAGS = [
    "trading_advice_request",  # buy/sell, signals, price targets, which leverage to use
    "complaint",               # customer expresses dissatisfaction and wants redress / formal complaint
    "kyc_outcome",             # disputes or asks to decide a verification / KYC result
    "aml_compliance",          # source of funds, third-party payments, sanctions, blocked for compliance
    "account_security",        # unauthorized access, stolen funds, phishing, hacked account
    "legal_threat",            # lawyer, regulator, court, chargeback threat, public exposure threat
    "prompt_injection",        # ticket tries to instruct the assistant / extract system info
]
RESPONSE_MODES = ["answer", "partial", "abstain", "decline"]

_TRIAGE_PROPS = {
    "language": {"type": "string", "description": "ISO 639-1 code of the customer's language, e.g. en, ru, es, ar."},
    "category": {"type": "string", "enum": CATEGORIES},
    "urgency": {"type": "string", "enum": URGENCY},
    "sentiment": {"type": "string", "enum": SENTIMENT},
    "risk_flags": {"type": "array", "items": {"type": "string", "enum": RISK_FLAGS}},
    "summary_en": {"type": "string", "description": "One-sentence English summary of what the customer needs."},
}
_TRIAGE_STAGED_PROPS = {
    **_TRIAGE_PROPS,
    "search_query_en": {"type": "string", "description": "Standalone English search query for the help-center knowledge base."},
}
_DRAFT_PROPS = {
    "response_mode": {"type": "string", "enum": RESPONSE_MODES},
    "draft_reply": {"type": "string", "description": "Reply to the customer, in the customer's language. Empty string only if response_mode is abstain."},
    "claims": {
        "type": "array",
        "description": "Every factual statement in draft_reply about policy, amounts, timelines, documents or procedures, each backed by a verbatim quote.",
        "items": {
            "type": "object",
            "properties": {
                "chunk_id": {"type": "string"},
                "quote": {"type": "string", "description": "Exact substring copied from that chunk's text (English)."},
            },
            "required": ["chunk_id", "quote"],
            "additionalProperties": False,
        },
    },
    "unanswered_questions": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Customer questions the knowledge base does not answer (English).",
    },
    "internal_note": {"type": "string", "description": "Short English note for the support agent: what to check, KB conflicts noticed, why escalation."},
}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


TRIAGE_SCHEMA = _obj(_TRIAGE_STAGED_PROPS)
DRAFT_SCHEMA = _obj(_DRAFT_PROPS)
SINGLE_SCHEMA = _obj({**_TRIAGE_PROPS, **_DRAFT_PROPS})
