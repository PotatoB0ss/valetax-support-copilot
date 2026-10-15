"""Security / abuse tests for the web UI. Real HTTP server on a random port, offline `mock` backend."""
import http.client
import json
import threading

import pytest

from copilot import web
from copilot.config import CONFIGS

PASSWORD = "test-password-123"


@pytest.fixture()
def server(monkeypatch):
    monkeypatch.setenv("COPILOT_PASSWORD", PASSWORD)
    monkeypatch.setenv("COPILOT_DAILY_LIMIT", "1000")
    srv = web.build_server(CONFIGS["mock"], port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def req(port, method, path, body=b"", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    out = (r.status, dict((k.lower(), v) for k, v in r.getheaders()), data)
    c.close()
    return out


def login(port, pw=PASSWORD, ip="1.2.3.4"):
    st, h, _ = req(port, "POST", "/login", f"password={pw}".encode(),
                   {"content-type": "application/x-www-form-urlencoded", "x-forwarded-for": ip})
    return st, h.get("set-cookie", "").split(";")[0]


def triage(port, cookie, payload, ip="1.2.3.4", ctype="application/json"):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return req(port, "POST", "/api/triage", body, {"content-type": ctype, "cookie": cookie, "x-forwarded-for": ip})


def test_unauthenticated_gets_login_and_api_is_closed(server):
    st, h, body = req(server, "GET", "/")
    assert st == 200 and b"Sign in" in body and b"Analyse ticket" not in body
    st, _, body = triage(server, "", {"text": "hi"})
    assert st == 401 and json.loads(body) == {"auth": False}


def test_forged_or_tampered_cookie_rejected(server):
    _, cookie = login(server)
    tampered = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")
    for c in ("cp_session=9999999999.deadbeef", tampered, 'cp_session="; x', "garbage"):
        assert triage(server, c, {"text": "hi"})[0] == 401


def test_login_logout_flow_and_cookie_flags(server):
    st, h, _ = req(server, "POST", "/login", f"password={PASSWORD}".encode(),
                   {"content-type": "application/x-www-form-urlencoded", "x-forwarded-proto": "https"})
    assert st == 303
    sc = h["set-cookie"]
    assert "HttpOnly" in sc and "SameSite=Strict" in sc and "Secure" in sc
    cookie = sc.split(";")[0]
    assert req(server, "GET", "/", headers={"cookie": cookie})[0] == 200
    st, h, _ = req(server, "POST", "/logout", headers={"cookie": cookie})
    assert st == 303 and "Max-Age=0" in h["set-cookie"]


def test_wrong_password_is_rate_limited(server):
    codes = [login(server, "wrong", ip="9.9.9.9")[0] for _ in range(web.LOGIN_ATTEMPTS + 2)]
    assert codes[: web.LOGIN_ATTEMPTS] == [401] * web.LOGIN_ATTEMPTS and codes[-1] == 429
    assert login(server, "wrong", ip="8.8.8.8")[0] == 401  # other clients unaffected


def test_lockout_also_blocks_the_correct_password(server):
    """Otherwise brute force just continues with a different status code until the right guess."""
    for _ in range(web.LOGIN_ATTEMPTS):
        login(server, "wrong", ip="6.6.6.6")
    st, cookie = login(server, PASSWORD, ip="6.6.6.6")
    assert st == 429 and not cookie


def test_successful_logins_do_not_count_towards_lockout(server):
    for _ in range(web.LOGIN_ATTEMPTS + 2):
        assert login(server, PASSWORD, ip="4.4.4.4")[0] == 303


def test_security_headers_present(server):
    _, h, _ = req(server, "GET", "/")
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert "python" not in h.get("server", "").lower()


def test_triage_happy_path(server):
    _, cookie = login(server)
    st, _, body = triage(server, cookie, {"text": "I was hacked, unauthorized withdrawal", "config": "mock"})
    assert st == 200 and json.loads(body)["routing"]["queue"] == "security"


def test_input_validation(server):
    _, cookie = login(server)
    assert triage(server, cookie, b"{not json")[0] == 400
    assert triage(server, cookie, b"[1,2]")[0] == 400
    assert triage(server, cookie, {"text": "   "})[0] == 400
    assert triage(server, cookie, {"text": "x" * (web.MAX_TICKET_CHARS + 1)})[0] == 400
    assert triage(server, cookie, {"text": "hi"}, ctype="application/x-www-form-urlencoded")[0] == 415  # CSRF via form


def test_oversized_body_rejected_without_reading(server):
    _, cookie = login(server)
    st, _, _ = req(server, "POST", "/api/triage", b"",
                   {"content-type": "application/json", "cookie": cookie, "content-length": str(web.MAX_BODY_BYTES + 1)})
    assert st == 413


def test_api_rate_limit_per_ip(server):
    _, cookie = login(server)
    codes = [triage(server, cookie, {"text": "min deposit?", "config": "mock"}, ip="5.5.5.5")[0] for _ in range(web.API_PER_MINUTE + 1)]
    assert codes[:-1] == [200] * web.API_PER_MINUTE and codes[-1] == 429


def test_daily_budget(monkeypatch):
    monkeypatch.setenv("COPILOT_PASSWORD", PASSWORD)
    monkeypatch.setenv("COPILOT_DAILY_LIMIT", "2")
    srv = web.build_server(CONFIGS["mock"], port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        _, cookie = login(port)
        codes = [triage(port, cookie, {"text": "min deposit?"}, ip=f"7.7.7.{i}")[0] for i in range(3)]
        assert codes == [200, 200, 429]
    finally:
        srv.shutdown()
        srv.server_close()


def test_unknown_paths_404(server):
    assert req(server, "GET", "/admin")[0] == 404
    assert req(server, "GET", "/../../etc/passwd")[0] == 404
    assert req(server, "POST", "/api/other")[0] == 404



def test_daily_usd_cap_blocks_after_spend():
    b = web.DailyBudget(max_requests=1000, max_usd=0.05)
    assert b.take() is None
    b.spend(0.03)
    assert b.take() is None
    b.spend(0.03)  # now $0.06 >= $0.05
    assert "spend limit" in (b.take() or "")


def test_daily_request_cap_and_negative_spend_ignored():
    b = web.DailyBudget(max_requests=2, max_usd=1.0)
    b.spend(-5)  # never lets a bad value "refund" the budget
    assert b.take() is None and b.take() is None
    assert "analysis limit" in (b.take() or "")


def test_budget_resets_next_day(monkeypatch):
    b = web.DailyBudget(max_requests=1, max_usd=1.0)
    monkeypatch.setattr(web.time, "strftime", lambda *a: "2026-01-01")
    assert b.take() is None and b.take() is not None
    monkeypatch.setattr(web.time, "strftime", lambda *a: "2026-01-02")
    assert b.take() is None


def _sse(port, cookie, payload, ip="3.3.3.3"):
    st, h, body = req(port, "POST", "/api/triage/stream", json.dumps(payload).encode(),
                      {"content-type": "application/json", "cookie": cookie, "x-forwarded-for": ip})
    events = []
    for block in body.decode().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
        if "data" in lines:
            events.append((lines.get("event"), json.loads(lines["data"])))
    return st, h, events


def test_stream_endpoint_requires_auth_and_returns_final_event(server):
    assert _sse(server, "", {"text": "hi"})[0] == 401
    _, cookie = login(server)
    st, h, events = _sse(server, cookie, {"text": "I was hacked, unauthorized withdrawal", "config": "mock"})
    assert st == 200 and h["content-type"].startswith("text/event-stream")
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert events[-1][0] == "final" and events[-1][1]["routing"]["queue"] == "security"


def test_stream_endpoint_shares_validation_and_rate_limit(server):
    _, cookie = login(server)
    assert _sse(server, cookie, {"text": "x" * (web.MAX_TICKET_CHARS + 1)})[0] == 400
    codes = [_sse(server, cookie, {"text": "min deposit?", "config": "mock"}, ip="2.2.2.2")[0] for _ in range(web.API_PER_MINUTE + 1)]
    assert codes[-1] == 429
