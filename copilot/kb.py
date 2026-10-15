"""Knowledge-base ingestion: Valetax help pages (HTML snapshots) -> citable chunks.

Design notes
- Pages are used *as they are* (task rule): no text is edited, fixed or merged.
- A chunk is the smallest unit an agent can verify in one glance: one FAQ Q&A pair,
  or the step list of a "how to" page, or the page intro.
- The deposit and withdraw pages carry an identical FAQ block. Identical chunks are
  stored once (stable id) and keep *every* URL they appear on, so a citation still
  points the agent to a real page, and retrieval is not polluted by duplicates.
- Every chunk has a content hash; `kb_version` is the hash of all chunks. Each
  co-pilot output records the kb_version it was produced with (auditability, and
  in Phase 2 it lets us re-run evals when the KB changes).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "kb_raw"
CHUNKS_PATH = ROOT / "data" / "kb" / "chunks.json"

PAGES = {
    "how-to-deposit": ("deposit", "How to Deposit", "https://valetax.com/how-to-deposit/"),
    "how-to-withdraw": ("withdraw", "How to Withdraw", "https://valetax.com/how-to-withdraw/"),
    "how-to-open-an-account": ("open-account", "How to Open an Account", "https://valetax.com/how-to-open-an-account/"),
    "how-to-verify-account": ("verify", "How to Verify Account", "https://valetax.com/how-to-verify-account/"),
}
# Marketing blocks that are on every page and carry no support policy.
BOILERPLATE_HEADINGS = {"all set to trade?", "trade from every device"}


@dataclass
class Chunk:
    id: str
    title: str
    text: str
    urls: list[str]
    pages: list[str]
    kind: str  # "intro" | "steps" | "faq"
    sha: str = ""
    tags: list[str] = field(default_factory=list)

    def render(self) -> str:
        """How the chunk is shown to the LLM (and to the agent in citations)."""
        return f'<chunk id="{self.id}" source="{self.urls[0]}">\n## {self.title}\n{self.text}\n</chunk>'


def _norm(s: str) -> str:
    return " ".join(s.replace("\xa0", " ").split())


def _slug(s: str, max_words: int = 7) -> str:
    words = re.findall(r"[a-z0-9]+", s.lower())
    stop = {"what", "is", "my", "the", "a", "an", "to", "do", "i", "can", "how", "of", "for", "should", "you", "are", "be", "will", "in", "into", "on"}
    kept = [w for w in words if w not in stop] or words
    return "-".join(kept[:max_words])


def parse_page(html: str, key: str) -> list[Chunk]:
    from bs4 import BeautifulSoup

    short, title, url = PAGES[key]
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        t.decompose()
    main = soup.find("main") or soup.body
    elements = [(el.name, _norm(el.get_text(" "))) for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li"])]
    elements = [(n, t) for n, t in elements if t]

    chunks: list[Chunk] = []
    intro, steps, faq = [], [], []
    mode = "intro"
    current_q = None
    for name, text in elements:
        low = text.lower()
        if name == "h1":
            continue
        if low.startswith("got a question on"):
            mode = "faq"
            continue
        if low in BOILERPLATE_HEADINGS:
            mode = "skip"
            continue
        if mode == "intro" and re.fullmatch(r"step \d+", low):
            mode = "steps"
        if mode == "intro":
            intro.append(text)
        elif mode == "steps":
            if re.fullmatch(r"step \d+", low):
                steps.append(f"{text.capitalize()}:")
            else:
                steps.append(text)
        elif mode == "faq":
            if name == "h4":
                current_q = text
                faq.append([text, []])
            elif current_q is not None:
                faq[-1][1].append(text)

    def mk(cid: str, ctitle: str, ctext: str, kind: str) -> Chunk:
        return Chunk(id=cid, title=ctitle, text=ctext, urls=[url], pages=[short], kind=kind)

    if intro:
        chunks.append(mk(f"{short}/intro", f"{title} — overview", " ".join(intro), "intro"))
    if steps:
        # Keep "Step N:" + heading on one line, sub-text on the next.
        lines, buf = [], ""
        for s in steps:
            if s.endswith(":") and s.lower().startswith("step"):
                if buf:
                    lines.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            lines.append(buf)
        chunks.append(mk(f"{short}/steps", f"{title} — steps", "\n".join(lines), "steps"))
    for q, answer in faq:
        chunks.append(mk(f"faq/{_slug(q)}", q, " ".join(answer), "faq"))
    return chunks


def build_chunks(raw_dir: Path = RAW_DIR) -> list[Chunk]:
    by_id: dict[str, Chunk] = {}
    for key in PAGES:
        html = (raw_dir / f"{key}.html").read_text(encoding="utf-8")
        for c in parse_page(html, key):
            c.sha = hashlib.sha256((c.title + "\n" + c.text).encode()).hexdigest()[:12]
            if c.id in by_id:
                prev = by_id[c.id]
                if prev.sha != c.sha:  # same question, different answer -> keep both, flag it
                    c.id = f"{c.id}@{c.pages[0]}"
                    by_id[c.id] = c
                    continue
                prev.urls += [u for u in c.urls if u not in prev.urls]
                prev.pages += [p for p in c.pages if p not in prev.pages]
                continue
            by_id[c.id] = c
    for c in by_id.values():
        c.tags = sorted(set(c.pages))
    return list(by_id.values())


def kb_version(chunks: list[Chunk]) -> str:
    return hashlib.sha256("".join(sorted(c.sha for c in chunks)).encode()).hexdigest()[:10]


def save_chunks(chunks: list[Chunk], path: Path = CHUNKS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"kb_version": kb_version(chunks), "chunks": [asdict(c) for c in chunks]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_chunks(path: Path = CHUNKS_PATH) -> list[Chunk]:
    if not path.exists():
        chunks = build_chunks()
        save_chunks(chunks, path)
        return chunks
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Chunk(**c) for c in data["chunks"]]


if __name__ == "__main__":
    cs = build_chunks()
    save_chunks(cs)
    print(f"{len(cs)} chunks, kb_version={kb_version(cs)} -> {CHUNKS_PATH}")
    for c in cs:
        print(f"- {c.id:45s} pages={','.join(c.pages)}")
