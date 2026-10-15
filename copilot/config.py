"""Run configurations and model prices. A configuration is what the business case chooses between."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# USD per 1M tokens (Anthropic first-party list prices, Oct 2026).
# Cache write = 1.25x input (5-min TTL), cache read = cache_read column.
PRICES = {
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50, "cache_read": 0.01},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20},
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20},
    "mock": {"in": 0.0, "out": 0.0, "cache_read": 0.0},
}


@dataclass(frozen=True)
class Config:
    name: str
    mode: str = "single"            # "single" (Phase 1) | "staged" (Phase 2: triage -> retrieve -> draft)
    model: str = "claude-sonnet-5-5"  # single-call model, or the drafting model in staged mode
    triage_model: str = "claude-haiku-5-5"
    effort: str = "low"
    retrieval: str = "full"          # "full" | "bm25"
    top_k: int = 6
    rules: bool = True               # OR deterministic risk rules into the LLM's flags
    cascade_model: str | None = None # re-run with this model when the draft is blocked by validation
    backend: str = "anthropic"       # "anthropic" | "mock"
    cache_ttl: str | None = None     # prompt-cache TTL: None = 5 min default; "1h" for sparse traffic (demo UI)
    description: str = ""

    def with_(self, **kw) -> "Config":
        return replace(self, **kw)


CONFIGS: dict[str, Config] = {c.name: c for c in [
    Config("p1-haiku", model="claude-haiku-5-5",
           description="Phase 1: one call, Haiku 5.5, whole KB in cached prompt"),
    Config("p1-sonnet", model="claude-sonnet-5-5",
           description="Phase 1: one call, Sonnet 5.5, whole KB in cached prompt"),
    Config("p1-opus", model="claude-opus-5-5",
           description="Phase 1: one call, Opus 5.5, whole KB in cached prompt"),
    Config("p1-haiku-cascade", model="claude-haiku-5-5", cascade_model="claude-sonnet-5-5",
           description="Haiku 5.5 first; re-draft with Sonnet 5.5 only if the validator blocks the draft"),
    Config("p2-staged", mode="staged", model="claude-sonnet-5-5", triage_model="claude-haiku-5-5", retrieval="bm25",
           description="Phase 2: Haiku triage + English query -> BM25 top-k -> Sonnet draft"),
    Config("p1-sonnet-norules", model="claude-sonnet-5-5", rules=False,
           description="Ablation: Sonnet 5.5 without deterministic risk rules"),
    Config("mock", model="mock", triage_model="mock", backend="mock",
           description="Offline rules-only baseline (keyword rules + top BM25 chunk). Tests/CI/demo without API key"),
]}

DEFAULT_CONFIG = "p1-sonnet"      # CLI / batch: the configuration the business case recommends
WEB_DEFAULT_CONFIG = "p1-opus"   # web demo: best judged draft quality


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Tiny .env loader (avoids a dependency). Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cost_usd(model: str, usage: dict) -> float:
    p = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (
        usage.get("input_tokens", 0) * p["in"]
        + usage.get("cache_creation_input_tokens", 0) * p["in"] * 1.25
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
        + usage.get("output_tokens", 0) * p["out"]
    ) / 1e6
