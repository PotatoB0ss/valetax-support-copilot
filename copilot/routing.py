"""Routing policy — deterministic, so it can be reviewed by Compliance line by line.

Every ticket gets a human: in Phase 1 nothing is auto-sent. The question is *which* human and in
what state the draft is:

  agent_review      draft is grounded and passed validation -> agent checks and sends (fast path)
  agent_manual      no usable draft (KB does not cover it / draft blocked / model error) -> agent writes
  complaints        complaint or legal threat -> complaints team decides; draft is an acknowledgement only
  compliance        KYC outcome or AML question -> compliance decides; draft is an acknowledgement only
  security          suspected account takeover / unauthorised activity -> security team, top priority

"Escalated" (a specialist queue) is the safety-critical decision measured in the eval.
"""
from __future__ import annotations

SPECIALIST_BY_FLAG = [  # first match wins (ordered by severity)
    ("account_security", "security"),
    ("aml_compliance", "compliance"),
    ("kyc_outcome", "compliance"),
    ("legal_threat", "complaints"),
    ("complaint", "complaints"),
]
SPECIALIST_QUEUES = {"security", "compliance", "complaints"}
PRIORITY = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4"}


def route(flags: set[str], urgency: str, response_mode: str | None, issues: list[dict], error: str | None) -> dict:
    reasons: list[str] = []
    queue = None
    for flag, q in SPECIALIST_BY_FLAG:
        if flag in flags:
            reasons.append(f"risk flag '{flag}' -> {q} (co-pilot never decides this outcome)")
            queue = queue or q
    blocking = [i for i in issues if i["severity"] == "block"]

    if error:
        draft_status = "none"
        reasons.append(f"co-pilot error: {error}")
    elif blocking:
        draft_status = "blocked"
        reasons.append("draft failed validation: " + "; ".join(f"{i['code']} ({i['detail']})" for i in blocking))
    elif response_mode == "abstain":
        draft_status = "none"
        reasons.append("knowledge base does not cover the question")
    elif response_mode == "partial" or any(i["severity"] == "warn" for i in issues):
        draft_status = "needs_edit"
        if response_mode == "partial":
            reasons.append("KB answers only part of the ticket; agent must complete it")
    else:
        draft_status = "ready"

    if "prompt_injection" in flags:
        reasons.append("ticket contains instructions aimed at the assistant (prompt injection) — treat with care")
    if "trading_advice_request" in flags:
        reasons.append("trading-advice request: draft declines it; agent must not add advice")

    if queue is None:
        queue = "agent_review" if draft_status in ("ready", "needs_edit") else "agent_manual"
    return {
        "queue": queue,
        "escalated": queue in SPECIALIST_QUEUES,
        "priority": "P1" if queue == "security" else PRIORITY.get(urgency, "P3"),
        "draft_status": draft_status,
        "reasons": reasons,
    }
