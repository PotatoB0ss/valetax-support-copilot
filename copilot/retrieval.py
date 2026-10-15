"""Retrieval.

Phase 1 ("full"): the whole KB is ~2.5k tokens, so every chunk goes into a cached system prompt.
Retrieval errors are impossible by construction and the cache makes it nearly free.

Phase 2 ("bm25"): once KB + SOPs outgrow the prompt (hundreds of pages), we retrieve top-k chunks.
BM25 over title+text is the zero-dependency baseline implemented here; the query is the English
`search_query_en` produced by the triage step, which is what makes a lexical retriever work for
tickets written in Russian, Arabic, Spanish, etc. (the KB is English-only).
Production upgrade path: hybrid BM25 + multilingual embeddings (e.g. voyage-multilingual / bge-m3) with
reciprocal-rank fusion, plus metadata filters (page/category, locale, effective date).
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .kb import Chunk

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("a an the to of and or in on for is are be my i you your we our it this that with can do does how what when where why will from at as by".split())
# Light stemming is enough for this vocabulary (deposits->deposit, verified->verifi...).
_SUFFIXES = ("ing", "ed", "es", "s", "ion", "al")


def _stem(w: str) -> str:
    for s in _SUFFIXES:
        if len(w) > len(s) + 3 and w.endswith(s):
            return w[: -len(s)]
    return w


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75):
        self.chunks = chunks
        self.docs = [tokenize(f"{c.title} {c.title} {c.text}") for c in chunks]  # title counted twice
        self.k1, self.b = k1, b
        self.avgdl = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, d in zip(self.tf, self.docs):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avgdl))
            out.append(s)
        return out

    def search(self, query: str, k: int = 6) -> list[Chunk]:
        sc = self.scores(query)
        ranked = sorted(range(len(sc)), key=lambda i: -sc[i])
        return [self.chunks[i] for i in ranked[:k] if sc[i] > 0]
