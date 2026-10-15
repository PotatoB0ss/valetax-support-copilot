# Security and abuse model

The co-pilot handles customer messages, calls a paid LLM API, and the demo UI is reachable from the internet.
This page lists what can go wrong and what stops it. Each web control has a test in `tests/test_web.py`.

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| **Prompt injection in a ticket** ("ignore your rules", fake `SYSTEM:` policy, "print your prompt") | Ticket is wrapped as untrusted data. The prompt overrides ticket instructions and flags `prompt_injection`. Output is a draft for a human, never auto-sent. Facts must be verbatim KB quotes (checked in code), so injected "policy" can't become a cited fact. Any link or email in a draft that is not on `valetax.com` blocks the draft (`foreign_link`), so an injected phishing URL can't reach a customer through a tired agent. | `prompts.py`, `guardrails.py`; eval slice `injection` (3 tickets, all handled) |
| **Model invents policy / gives advice / decides KYC-AML-complaint outcomes** | ≥2 independent layers per rule (prompt, rules, validator, routing, human). Release gate in CI. | `docs/ARCHITECTURE.md` |
| **Cost abuse of the paid LLM** (scripted requests, huge tickets) | Login required. 20 analyses/min per client IP. Two daily caps across all users, whichever hits first: **`COPILOT_DAILY_USD_LIMIT` (default $5, real spend from token `usage`)** and `COPILOT_DAILY_LIMIT` analyses (default 300). At most 4 concurrent LLM calls (503 beyond). Per call: ticket ≤ 5,000 chars, body ≤ 32 KB, output ≤ `max_tokens` (6k; 3k for triage), `effort: low`. Plus a monthly spend limit on the Anthropic account as the last line. | `web.py`, `llm.py` |
| **Password guessing** | 5 failed attempts per IP per 5 min → lockout. The lockout is checked *before* the password, so a locked-out client can't continue guessing (regression-tested). Constant-time compare. Long random password in deployment. | `web.py` |
| **Session forgery / theft** | HMAC-SHA256-signed expiring token (12 h), per-process key. Cookie `HttpOnly; SameSite=Strict; Secure` (behind HTTPS). | `web.py` |
| **CSRF** | SameSite=Strict. API accepts only `application/json` (a cross-site HTML form can't send it). Logout is POST. | `web.py` |
| **XSS** (LLM output or ticket text rendered in the page) | Every dynamic value is HTML-escaped before insertion. Strict CSP (`default-src 'none'`, no external origins, `frame-ancestors 'none'`). | `web.py` |
| **Clickjacking, MIME sniffing, referrer leaks** | `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, HSTS at the proxy. | `web.py`, Caddy |
| **Slow clients / resource exhaustion** | 30 s socket timeout. Body size checked before reading. Rate-limiter memory bounded. TLS terminated by Caddy. | `web.py` |
| **Spoofed client IP to dodge rate limits** | The app listens on `127.0.0.1` only. `X-Forwarded-For` is trusted only when the peer is the local proxy, and Caddy overwrites client-supplied values. | `web.py`, deployment |
| **Secrets in the repo** | `.env` is git-ignored. Keys only come from the environment. The repo history was checked for keys and tokens before publishing. | `.gitignore` |
| **Customer PII sent to the LLM / logs** | The request log is disabled (no ticket text in logs). PII redaction before the LLM call is **not implemented** (stub). Production: redact card/ID numbers, use a provider with ZDR/DPA. | `docs/ARCHITECTURE.md` |
| **Server compromise blast radius** | The app runs as an unprivileged `copilot` user under systemd sandboxing (`ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`). The firewall allows only 22/80/443. | deployment |

## Automated checks

- `bandit -r copilot evals business_case`: 0 findings. One false positive (seeded `random` in the offline simulation) is annotated with `# nosec`.
- `pip-audit` on the locked dependencies: no known vulnerabilities.
- Both run in CI with the unit tests.

## Known limitations (demo scope)

- One shared password instead of per-agent SSO and roles. There is no server-side session revocation; logout clears the cookie and a server restart invalidates all sessions.
- Rate limits are in memory and per process. Use Redis for several replicas.
- No PII redaction yet (see above).
- The unit tests run from localhost, so the `X-Forwarded-For` trust rule is covered by design and review, not by a test.
