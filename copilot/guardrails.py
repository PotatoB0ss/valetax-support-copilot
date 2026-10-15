"""Deterministic guardrails around the LLM.

Two layers, both plain code so they are cheap, testable and auditable:

1. `detect_risks(ticket)` — multilingual keyword rules that run *before/alongside* the LLM. Their flags are
   OR-ed with the LLM's flags. They exist for recall on the safety-critical routes (trading advice,
   complaints, KYC/AML, security): if the model misses a flag, the rule still routes the ticket.
   They are intentionally simple; precision is the LLM's job.

2. `validate_draft(...)` — checks the LLM's draft against the KB *after* generation:
   citations exist, quotes are really in the cited chunk, every number in the reply is grounded,
   and no trading-advice / outcome-promise language slipped through. Blocking issues stop the draft
   from being offered as "ready"; the agent sees why.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .kb import Chunk

# ---------------------------------------------------------------- 1. risk detection on the ticket
# Patterns are lower-cased, matched on NFKC-normalised lower-case text. en / ru / es / pt / ar / id / vi / ms.
RISK_PATTERNS: dict[str, list[str]] = {
    "trading_advice_request": [
        r"\bshould i (buy|sell|go long|go short|open|close|enter|exit|hold)\b",
        r"\b(buy|sell) (signal|signals)\b", r"\bsignals?\b.*\b(gold|xau|eur|usd|btc|forex)\b",
        r"\bprice target\b", r"\btarget price\b", r"\b(which|what|best|recommended?) leverage\b.*\b(use|choose|pick|should|best)\b",
        r"\bwhat leverage should\b", r"\bbest (pair|strategy|time to (buy|sell|trade))\b",
        r"\bwill (gold|xauusd|eurusd|bitcoin|btc|the (price|market)) (go|rise|fall|drop|move)\b",
        r"\bwhere (is|will) (gold|eurusd|the market) (go|head)", r"\btrading (tips|advice|recommendation)",
        r"\bгде (купить|продать)\b", r"\b(купить|продавать|покупать|продать) ли\b", r"\bсигнал", r"\bкуда пойд[её]т\b",
        r"\bкакое плечо (выбрать|лучше|поставить|ставить)", r"\bстоит ли (\w+ )?(купить|продать|входить|покупать|продавать)",
        r"\bdebo (comprar|vender)\b", r"\bseñales? de (trading|compra|venta)", r"\bdevo (comprar|vender)\b",
        r"هل (يجب|ينبغي) (أن )?(أشتري|أبيع)", r"\bsinyal (trading|beli|jual)\b", r"\bharus (beli|jual)\b",
        r"\bnên (mua|bán)\b", r"\btín hiệu\b",
    ],
    "complaint": [
        r"\bcomplain", r"\bscam", r"\bfraud(ulent|sters?)?\b", r"\bunacceptable\b", r"\bworst\b", r"\bthieves\b",
        r"\bstealing my\b", r"\bfile a (formal )?complaint\b", r"\bdisgust", r"\bridiculous\b",
        r"\bжалоб", r"\bмошенни", r"\bразвод", r"\bворы\b", r"\bпретензи", r"\bбезобрази", r"\bобман",
        r"\bqueja\b", r"\breclamaci[oó]n\b", r"\bestafa", r"\bladr[oó]n", r"\bgolpe\b", r"\breclama[çc][aã]o\b",
        r"شكوى", r"احتيال", r"نصب", r"\bpenipu", r"\bkeluhan\b", r"\blừa đảo\b", r"\bkhiếu nại\b",
    ],
    "kyc_outcome": [
        r"\b(verification|kyc|documents?|account) (was |were |has been |got )?(rejected|declined|denied|refused)",
        r"\bwhy (was|is) my (verification|kyc|document|account verification)",
        r"\b(approve|speed up|expedite) my (verification|kyc|documents?)",
        r"\bverification (is )?(still )?(pending|taking|not (done|approved|complete))",
        r"\bstill (not )?verified\b", r"\bnot verified yet\b",
        r"\bверификаци\w* (отклон|не прош|до сих пор|затянул)", r"\bотклонил\w* (документ|верификац)",
        r"\bverificaci[oó]n (rechazada|pendiente)", r"\bverifica[çc][aã]o (rejeitada|pendente)",
        r"رفض.{0,20}(التحقق|المستندات|الوثائق)", r"\bverifikasi (ditolak|belum)",
    ],
    "aml_compliance": [
        r"\bsource of (funds|wealth)\b", r"\b(friend|brother|sister|wife|husband|father|mother|someone else|another person|third[- ]party)'?s? (card|account|wallet)\b",
        r"\b(card|wallet|account) (of|belonging to) (my )?(friend|brother|wife|husband|father|mother|someone else)\b",
        r"\b(account|funds) (is |are |was |were |has been )?(frozen|blocked|suspended)\b", r"\bsanction", r"\baml\b",
        r"\bmoney laundering\b", r"\bчужой карт", r"\bкарт\w* (друга|брата|жены|мужа|отца|мамы|сестры)", r"\bисточник (средств|дохода)",
        r"\b(заблокир|заморо[зж])\w*", r"\bcuenta (bloqueada|congelada)\b", r"\bconta (bloqueada|congelada)\b",
        r"(تجميد|حظر|تم حظر|مجمد)", r"\bdibekukan\b", r"\bdiblokir\b",
    ],
    "account_security": [
        r"\bhack(ed|er)?\b", r"\bunauthori[sz]ed\b", r"\bsomeone (logged|accessed|withdrew|took)\b", r"\bstolen\b",
        r"\bi did(n't| not) (make|request|authori[sz]e) (this|that|a|the) (withdrawal|transaction|transfer|trade)", r"\bphishing\b",
        r"\bвзлом", r"\bукрал", r"\bне я (выводил|снимал|делал)", r"\bmi cuenta fue hackeada\b", r"\bhackead",
        r"اختراق", r"\bdiretas\b", r"\bbị hack\b",
    ],
    "legal_threat": [
        r"\blawyer\b", r"\battorney\b", r"\bsue\b", r"\blawsuit\b", r"\bcourt\b", r"\bregulator\b", r"\bfinancial commission\b",
        r"\bchargeback\b", r"\bpolice\b", r"\bombudsman\b", r"\b(post|expose) (this|you) (on|to) (social|twitter|facebook|trustpilot|forex peace|fpa)",
        r"\bюрист", r"\bадвокат", r"\bсуд\b", r"\bв суд\b", r"\bрегулятор", r"\bполици", r"\bчарджбек", r"\bабогado\b", r"\bdemanda\b",
        r"\badvogado\b", r"\bprocesso\b", r"محامي", r"الشرطة", r"\bpengacara\b", r"\bluật sư\b",
    ],
    "prompt_injection": [
        r"ignore (all |any )?(previous|prior|above|your) (instructions|rules|prompt)", r"\bsystem prompt\b",
        r"\byou are now\b", r"\bdeveloper mode\b", r"\bact as\b", r"\bjailbreak\b", r"\bpretend (to be|you are)\b",
        r"игнорируй (все |предыдущие )?(инструкции|правила)", r"\bсистемн\w+ промпт",
    ],
}
_COMPILED = {flag: [re.compile(p, re.I) for p in pats] for flag, pats in RISK_PATTERNS.items()}


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


def detect_risks(ticket: str) -> dict[str, list[str]]:
    """Return {flag: [matched snippets]} for every rule that fires."""
    t = normalise(ticket)
    hits: dict[str, list[str]] = {}
    for flag, pats in _COMPILED.items():
        for p in pats:
            m = p.search(t)
            if m:
                hits.setdefault(flag, []).append(m.group(0))
    return hits


# ---------------------------------------------------------------- 2. draft validation
@dataclass
class Issue:
    code: str
    severity: str  # "block" | "warn"
    detail: str

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "detail": self.detail}


_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_LIST_MARKER = re.compile(r"(?m)^\s*(\d{1,2})[.)]\s")
_ADVICE_IN_DRAFT = [
    re.compile(p, re.I) for p in [
        r"\b(you should|i recommend|we recommend|i suggest|we suggest|i advise|we advise|best to)\b.{0,60}\b(buy|sell|go long|go short|leverage of|1:\d+|position|entry|stop[- ]loss)\b",
        r"\b(good|right|best) time to (buy|sell|enter|trade)\b",
        r"\b(price|gold|eurusd|xauusd|bitcoin|market) (will|is going to|is likely to) (rise|fall|drop|go up|go down|reach)\b",
        r"\b(рекомендую|советую|стоит)\s+(купить|продать|покупать|продавать|выбрать плечо|плечо)",
        r"\b(le recomiendo|te recomiendo|recomendamos)\s+(comprar|vender|apalancamiento)",
    ]
]
# Script check for languages with a distinctive alphabet: a reply with zero characters of that script is
# certainly in the wrong language. (Latin-script languages need a language-ID model; see ARCHITECTURE.)
_SCRIPT = {
    "ru": r"[а-яА-ЯёЁ]", "uk": r"[а-яА-ЯіїєІЇЄ]", "ar": r"[؀-ۿ]", "fa": r"[؀-ۿ]", "ur": r"[؀-ۿ]",
    "th": r"[฀-๿]", "zh": r"[一-鿿]", "ja": r"[぀-ヿ一-鿿]", "ko": r"[가-힯]",
    "hi": r"[ऀ-ॿ]", "vi": r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]",
}
_NEGATED = re.compile(
    r"\b(whether|if|not|unable|cannot|can't|never|no)\b|ли\b|\bне\b|\bsi\b|\bno podemos\b|\bnão\b|\btidak\b|\bkhông\b|لا|هل",
    re.I,
)
_CONDITIONAL = re.compile(r"\b(once|when|after|until|if|as soon as)\b", re.I)
_OUTCOME_PROMISE = [
    re.compile(p, re.I) for p in [
        r"\byour (account|verification|documents?) (will be|has been|is) (approved|verified|unblocked|unfrozen|accepted)\b",
        r"\bwe will (refund|compensate|unblock|unfreeze|approve|reverse)\b",
        r"\b(your )?complaint (is|has been) (upheld|accepted|resolved in your favou?r)\b",
        r"\b(it was|this is) (a|our) mistake\b",
    ]
]


def _numbers(text: str) -> set[str]:
    t = text.translate(_ARABIC_INDIC)
    return {n.replace(",", ".") for n in _NUM.findall(t)}


def _quote_norm(s: str) -> str:
    s = normalise(s)
    s = re.sub(r"[^\w\s:%$.]", " ", s)
    return " ".join(s.split())


def _token_overlap(quote: str, text: str) -> float:
    q = _quote_norm(quote).split()
    if not q:
        return 0.0
    words = set(_quote_norm(text).split())
    return sum(w in words for w in q) / len(q)


def validate_draft(draft: dict, ticket: str, provided: list[Chunk], risk_flags: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    by_id = {c.id: c for c in provided}
    reply = draft.get("draft_reply") or ""
    mode = draft.get("response_mode")

    if mode != "abstain" and not reply.strip():
        issues.append(Issue("empty_draft", "block", f"response_mode={mode} but draft is empty"))

    cited: list[Chunk] = []
    for cl in draft.get("claims") or []:
        c = by_id.get(cl.get("chunk_id", ""))
        if c is None:
            issues.append(Issue("unknown_citation", "block", f"cites '{cl.get('chunk_id')}', not in the KB given to the model"))
            continue
        cited.append(c)
        q = _quote_norm(cl.get("quote", ""))
        hay = _quote_norm(c.title + " " + c.text)
        if q and q in hay:
            continue
        ov = _token_overlap(cl.get("quote", ""), c.title + " " + c.text)
        if ov >= 0.8:
            issues.append(Issue("paraphrased_quote", "warn", f"{c.id}: quote not verbatim (overlap {ov:.0%})"))
        else:
            issues.append(Issue("unsupported_claim", "block", f"{c.id}: quote not found in chunk: {cl.get('quote','')[:80]!r}"))

    # Every number in the reply must come from a cited chunk or from the customer's own ticket.
    allowed = _numbers(ticket)
    for c in cited:
        allowed |= _numbers(c.title + " " + c.text)
    markers = set(_LIST_MARKER.findall(reply.translate(_ARABIC_INDIC)))
    for n in sorted(_numbers(reply) - allowed - markers):
        issues.append(Issue("ungrounded_number", "block", f"'{n}' appears in the reply but not in any cited chunk or the ticket"))

    for p in _ADVICE_IN_DRAFT:
        for m in p.finditer(reply):
            # "...whether you should buy gold, we cannot advise" is a refusal, not advice.
            if _NEGATED.search(reply[max(0, m.start() - 60): m.start()]):
                continue
            issues.append(Issue("trading_advice_in_draft", "block", m.group(0)[:80]))
            break
    if risk_flags & {"complaint", "kyc_outcome", "aml_compliance", "account_security", "legal_threat"}:
        for p in _OUTCOME_PROMISE:
            for m in p.finditer(reply):
                # "once your account is verified, you can withdraw" is conditional, not a promise.
                if _CONDITIONAL.search(reply[max(0, m.start() - 25): m.start()]):
                    continue
                issues.append(Issue("outcome_promise", "block", m.group(0)[:80]))
                break

    lang = (draft.get("language") or "").lower()
    if reply.strip() and lang in _SCRIPT and not re.search(_SCRIPT[lang], reply):
        issues.append(Issue("wrong_language", "block", f"customer language is '{lang}' but the reply is not written in it"))

    if mode == "answer" and draft.get("unanswered_questions"):
        issues.append(Issue("mode_inconsistent", "warn", "mode=answer but unanswered_questions is not empty"))
    if mode in ("answer", "partial") and not draft.get("claims"):
        issues.append(Issue("no_citations", "warn", f"mode={mode} without any KB claim"))
    return issues
