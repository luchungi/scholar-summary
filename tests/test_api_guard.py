"""The local API refuses other websites (decision 0022)."""

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend.review_scheduler import ReviewScheduler
from backend.security import LocalOnlyMiddleware, rejection_reason

GOOD_HOST = {"host": "localhost:8000"}


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(LocalOnlyMiddleware)
    app.state.hits = []

    @app.get("/api/teardown")
    def teardown():
        app.state.hits.append("teardown")
        return {"ok": True}

    @app.post("/api/upload")
    def upload():
        app.state.hits.append("upload")
        return {"ok": True}

    @app.get("/api/stream")
    def stream():
        return StreamingResponse(iter(["data: one\n\n", "data: two\n\n"]), media_type="text/event-stream")

    @app.get("/page")
    def page():
        return {"ok": True}

    test_client = TestClient(app, base_url="http://localhost:8000")
    test_client.hits = app.state.hits
    return test_client


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Origin": "http://localhost:9999"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
def test_cross_site_get_cannot_trigger_state_change(client, headers):
    assert client.get("/api/teardown", headers=headers).status_code == 403
    assert client.hits == []


def test_cross_site_form_post_is_refused(client):
    response = client.post("/api/upload", headers={"Origin": "https://evil.example"},
                           files={"file": ("a.pdf", b"x", "application/pdf")})
    assert response.status_code == 403 and client.hits == []


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "localhost.evil.example", ""])
def test_dns_rebinding_host_is_refused(client, host):
    assert client.get("/page", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("headers", [
    {"Origin": "http://localhost:8000"},
    {"Origin": "http://127.0.0.1:5173"},
    {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"},
    {"Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Site": "none"},
    {},
])
def test_the_app_itself_still_works(client, headers):
    assert client.get("/api/teardown", headers=headers).status_code == 200


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "localhost"])
def test_local_hosts_are_allowed(host):
    assert rejection_reason("/api/x", {"host": host}) is None


def test_streaming_and_security_headers(client):
    response = client.get("/api/stream")
    assert response.text == "data: one\n\ndata: two\n\n"
    policy = response.headers["content-security-policy"]
    assert "img-src 'self' data:" in policy and "script-src 'self'" in policy
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_real_app_refuses_other_sites():
    from backend.main import app
    client = TestClient(app, base_url="http://localhost:8000")
    assert client.get("/api/profile", headers={"Origin": "https://evil.example"}).status_code == 403
    preflight = client.options("/api/profile/save", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 403 and "access-control-allow-origin" not in preflight.headers


def test_scheduler_never_prefills_two_prompts_at_once():
    active, peak, order = 0, 0, []
    lock = threading.Lock()

    def enter():
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1

    def prepare(item, tag, release):
        enter()
        order.append((item, "decided"))
        release()
        time.sleep(0.02)  # the network search runs without the lock

    def review(item, tag, on_first_token):
        enter()
        order.append((item, "review"))
        on_first_token()
        time.sleep(0.01)
        return item

    done = []
    scheduler = ReviewScheduler(review, lambda item, tag, result, error: done.append((item, error)),
                                max_concurrency=4, token_budget=1000, cooldown_seconds=0,
                                retry_delay_seconds=0, log=lambda m: None, prepare_fn=prepare)
    for item in range(4):
        scheduler.submit(item, 10)
    scheduler.close()
    scheduler.run()

    assert peak == 1 and sorted(done, key=lambda d: d[0]) == [(i, None) for i in range(4)]
    for item in range(4):
        assert order.index((item, "decided")) < order.index((item, "review"))


def test_prepare_failure_is_a_failed_attempt():
    errors = []
    reviewed = []

    def prepare(item, tag, release):
        raise ValueError("bad")

    scheduler = ReviewScheduler(lambda *a: reviewed.append(a), lambda i, t, r, e: errors.append(e),
                                max_concurrency=1, token_budget=100, cooldown_seconds=0,
                                retry_delay_seconds=0, log=lambda m: None, prepare_fn=prepare)
    scheduler.submit("x", 10)
    scheduler.close()
    scheduler.run()
    assert len(errors) == 1 and isinstance(errors[0], ValueError) and not reviewed
    assert scheduler._prefill_lock.acquire(blocking=False)
