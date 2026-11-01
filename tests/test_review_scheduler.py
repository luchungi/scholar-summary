"""
Tests for the token-budget review scheduler (decision 0012) and the thread-safe URL
rule writes that parallel triage relies on.

All tests here are offline: reviews are stubbed with events and sleeps, so no LLM
server is contacted. The rules test writes to a throwaway file.
"""

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
import paper_retriever
from backend.review_scheduler import ReviewScheduler, estimate_review_tokens, is_capacity_abort


class Recorder:
    """Stub review_fn/on_done pair that records timing and concurrency."""

    def __init__(self, duration=0.05, errors=None):
        self.duration = duration
        self.errors = dict(errors or {})   # item -> list of exceptions to raise in turn
        self.lock = threading.Lock()
        self.starts = []                    # items in start order
        self.running = set()
        self.overlaps = []                  # snapshot of running set at each start
        self.done = {}                      # item -> (result, error)

    def review(self, item, tag, on_first_token):
        with self.lock:
            self.starts.append(item)
            self.running.add(item)
            self.overlaps.append(set(self.running))
        try:
            on_first_token()
            time.sleep(self.duration)
            errs = self.errors.get(item)
            if errs:
                raise errs.pop(0)
            return f"report-{item}"
        finally:
            with self.lock:
                self.running.discard(item)

    def on_done(self, item, tag, result, error):
        with self.lock:
            assert item not in self.done, "on_done called twice"
            self.done[item] = (result, error)


def make(rec, max_concurrency=2, budget=40_000, **kw):
    kw.setdefault("cooldown_seconds", 0)
    kw.setdefault("retry_delay_seconds", 0)
    return ReviewScheduler(rec.review, rec.on_done, max_concurrency, budget, log=lambda s: None, **kw)


def run_all(rec, papers, max_concurrency=2, budget=40_000, **kw):
    sched = make(rec, max_concurrency, budget, **kw)
    for item, tokens in papers:
        sched.submit(item, tokens, label=item)
    sched.close()
    sched.run()
    return sched


def test_two_small_papers_run_together():
    rec = Recorder(duration=0.2)
    sched = run_all(rec, [("a", 15_000), ("b", 15_000)])
    assert sched.peak_concurrency == 2
    assert {"a", "b"} in rec.overlaps
    assert all(err is None for _, err in rec.done.values())


def test_pair_over_budget_runs_one_at_a_time():
    rec = Recorder(duration=0.1)
    sched = run_all(rec, [("long", 30_000), ("mid", 20_000)])
    assert sched.peak_concurrency == 1
    assert rec.starts == ["long", "mid"]


def test_paper_over_budget_alone_still_runs():
    rec = Recorder()
    run_all(rec, [("huge", 90_000)])
    assert rec.done["huge"] == ("report-huge", None)


def test_longest_first_and_short_papers_backfill():
    rec = Recorder(duration=0.1)
    # Budget 40k: the 30k paper starts first; the 25k can't join it, the 8k can.
    run_all(rec, [("short", 8_000), ("mid", 25_000), ("long", 30_000)])
    assert rec.starts[0] == "long"
    assert rec.starts[1] == "short"
    assert {"long", "short"} in rec.overlaps
    assert not any({"long", "mid"} <= s for s in rec.overlaps)


def test_concurrency_cap_one_never_overlaps():
    rec = Recorder(duration=0.05)
    sched = run_all(rec, [(f"p{i}", 5_000) for i in range(4)], max_concurrency=1)
    assert sched.peak_concurrency == 1
    assert len(rec.done) == 4


def test_memory_abort_alongside_another_review_drops_to_one_at_a_time():
    abort = ConnectionError("Details: Request aborted: process memory limit exceeded (usage 49.7 GB)")
    rec = Recorder(duration=0.1, errors={"a": [abort]})
    sched = run_all(rec, [("a", 15_000), ("b", 15_000), ("c", 15_000), ("d", 15_000)])
    assert sched.abort_retries == 1
    assert rec.done["a"] == ("report-a", None)
    assert len(rec.done) == 4
    # After the abort, no review starts while another is running.
    first_retry_idx = rec.starts.index("a", 1)
    assert all(len(s) == 1 for s in rec.overlaps[first_retry_idx:])
    # The aborted paper went back to the front: it runs before any paper still waiting
    # at the time of the abort ("c" may legitimately have started just before it).
    assert first_retry_idx < rec.starts.index("d")


def test_third_capacity_error_reports_failure():
    abort = RuntimeError("Request aborted: process memory limit exceeded")
    rec = Recorder(errors={"a": [abort, abort, abort]})
    sched = run_all(rec, [("a", 15_000)])
    result, error = rec.done["a"]
    assert result is None and error is abort
    assert sched.abort_retries == 2
    assert rec.starts == ["a", "a", "a"]


def test_rejection_with_nothing_else_running_keeps_concurrency():
    """A rejection on a lone review is the server's memory settling, not concurrency."""
    reject = RuntimeError("Error code: 400 - {'code': 'prefill_memory_exceeded'}")
    rec = Recorder(duration=0.1, errors={"long": [reject]})
    sched = run_all(rec, [("long", 39_000), ("b", 15_000), ("c", 15_000)])
    assert rec.done["long"] == ("report-long", None)
    assert sched.abort_retries == 1
    assert {"b", "c"} in rec.overlaps


def test_cooldown_after_long_review():
    starts = {}

    def review(item, tag, on_first_token):
        starts[item] = time.monotonic()
        on_first_token()
        time.sleep(0.05)
        return item

    ends = {}
    sched = ReviewScheduler(review, lambda item, *a: ends.setdefault(item, time.monotonic()),
                            2, 40_000, log=lambda s: None,
                            cooldown_tokens=30_000, cooldown_seconds=0.5, retry_delay_seconds=0)
    sched.submit("long", 35_000, "long")
    sched.submit("short", 10_000, "short")
    sched.close()
    sched.run()
    assert starts["short"] - ends["long"] >= 0.45


def test_retry_waits_for_the_retry_delay():
    abort = RuntimeError("Error code: 507 - aborted before scheduling")
    rec = Recorder(duration=0.01, errors={"a": [abort]})
    times = []
    orig = rec.review

    def review(item, tag, on_first_token):
        times.append(time.monotonic())
        return orig(item, tag, on_first_token)

    rec.review = review
    run_all(rec, [("a", 15_000)], retry_delay_seconds=0.4)
    assert times[1] - times[0] >= 0.4


def test_other_errors_are_not_retried():
    err = ValueError("bad request: context length exceeded")
    rec = Recorder(errors={"a": [err]})
    sched = run_all(rec, [("a", 15_000), ("b", 15_000)])
    assert rec.done["a"] == (None, err)
    assert rec.done["b"] == ("report-b", None)
    assert sched.abort_retries == 0


def test_submit_while_running():
    rec = Recorder(duration=0.05)
    sched = make(rec)
    runner = threading.Thread(target=sched.run)
    runner.start()
    for i in range(3):
        time.sleep(0.02)
        sched.submit(f"p{i}", 10_000, label=f"p{i}")
    sched.close()
    runner.join(timeout=5)
    assert not runner.is_alive()
    assert len(rec.done) == 3


def test_prefill_never_overlaps():
    """A second review may not start its request until the first has its first token."""
    events = []
    lock = threading.Lock()

    def review(item, tag, on_first_token):
        with lock:
            events.append(("prefill_start", item))
        time.sleep(0.1)
        with lock:
            events.append(("prefill_end", item))
        on_first_token()
        time.sleep(0.1)
        return item

    sched = ReviewScheduler(review, lambda *a: None, 2, 40_000, log=lambda s: None,
                            cooldown_seconds=0, retry_delay_seconds=0)
    sched.submit("a", 10_000, "a")
    sched.submit("b", 10_000, "b")
    sched.close()
    sched.run()
    in_prefill = 0
    for kind, _ in events:
        in_prefill += 1 if kind == "prefill_start" else -1
        assert in_prefill <= 1


@pytest.mark.parametrize("msg, expected", [
    ("Request aborted: process memory limit exceeded (usage 50.1 GB)", True),
    ("Error code: 503 - server busy", True),
    ("Model is overloaded", True),
    ("Error code: 400 - prefill memory guard rejected this prompt", True),
    ("Error code: 409 - Model is busy; cannot start work while unload is pending", True),
    ("Error code: 507 - Request aborted before scheduling", True),
    ("Request timed out.", False),
    ("Error code: 400 - max_tokens 4096 exceeds the limit", False),
    ("Error code: 400 - context length exceeded", False),
])
def test_is_capacity_abort(msg, expected):
    assert is_capacity_abort(RuntimeError(msg)) is expected


def test_estimate_review_tokens_includes_overhead_and_reserve():
    text = "x" * int(10_000 * config.CHARS_PER_TOKEN)
    est = estimate_review_tokens(text)
    assert est > 10_000 + config.REVIEW_OUTPUT_RESERVE_TOKENS


def test_parallel_rule_writes_keep_every_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_retriever, "URL_RULES_PATH", tmp_path / "rules.json")
    paper_retriever.save_rules({"existing.org": {"rules": [{"type": "direct"}]}})

    def write(i):
        paper_retriever.set_domain_rule(f"d{i}.org", [{"type": "direct"}])

    threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rules = paper_retriever.load_rules()
    assert "existing.org" in rules
    assert all(f"d{i}.org" in rules for i in range(20))


# ---------------------------------------------------------------------------
# End-to-end batch run with stubbed retrieval and LLM calls
# ---------------------------------------------------------------------------

def test_batch_run_triage_feeds_reviews_and_records_outcomes(tmp_path, monkeypatch):
    import queue
    from sqlmodel import SQLModel, Session, create_engine, select
    import backend.services as services
    from backend.models import Paper, Run

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(services, "engine", engine)
    # pytest swaps sys.stdout per test; put back the router services installs at import
    # so LogCapture can route each worker thread's prints to the run queue.
    monkeypatch.setattr(sys, "stdout", services._stdout_router)
    monkeypatch.setattr(config, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "RELEVANCE_GATE_ENABLED", True)
    monkeypatch.setattr(config, "REVIEW_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(config, "REVIEW_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(services, "ensure_interests_file", lambda: "interests")
    monkeypatch.setenv("MAX_CONCURRENT_REVIEWS", "2")

    def retrieve(url):
        if "missing" in url:
            return None
        return {"text": f"text of {url} " * 50, "source": "pdf", "raw_chars": 1000, "truncated": False}

    calls = {"aborted": False}

    def report(title, url, text, interests, access, on_first_token=None):
        if on_first_token:
            on_first_token()
        if "flaky" in url and not calls["aborted"]:
            calls["aborted"] = True
            raise ConnectionError("Details: Request aborted: process memory limit exceeded")
        time.sleep(0.05)
        return "### 6. Ratings\n<ratings><quality_rating>3.0</quality_rating>" \
               "<relevance_rating>4.0</relevance_rating></ratings>"

    monkeypatch.setattr(services.paper_retriever, "retrieve_paper", retrieve)
    monkeypatch.setattr(services.agent, "assess_relevance",
                        lambda title, snippet, interests: (1.0, "off topic") if "offtopic" in title else (4.0, "fits"))
    monkeypatch.setattr(services.agent, "generate_paper_report", report)

    with Session(engine) as session:
        run = Run(status="running", emails_fetched=0)
        session.add(run)
        session.commit()
        run_id = run.id

    papers = [
        {"title": "Good paper one", "url": "https://x.org/good1"},
        {"title": "Flaky paper", "url": "https://x.org/flaky"},
        {"title": "An offtopic paper", "url": "https://x.org/offtopic"},
        {"title": "Missing paper", "url": "https://x.org/missing"},
        {"title": "Good paper two", "url": "https://x.org/good2"},
    ]
    q = queue.Queue()
    services.run_paper_processing_task(run_id, papers, q)

    with Session(engine) as session:
        rows = {p.url.rsplit("/", 1)[1]: p for p in session.exec(select(Paper)).all()}
        run = session.get(Run, run_id)
    assert rows["good1"].status == "success" and rows["good1"].quality_rating == 3.0
    assert rows["good2"].status == "success"
    assert rows["flaky"].status == "success"            # retried once after the abort
    assert rows["offtopic"].status == "skipped"
    assert rows["missing"].status == "failed"
    assert rows["missing"].skip_reason == "Could not retrieve the paper text."
    assert run.papers_processed == 3 and run.papers_failed == 1 and run.status == "failed"

    log = []
    while not q.empty():
        item = q.get()
        if item is not None:
            log.append(item)
    log = "".join(log)
    assert "Retry 1/2" in log
    assert "Triage finished: 3 of 5 paper(s) queued" in log


@pytest.mark.parametrize("framework, cache_on, expected", [
    ("omlx", False, 30.0),
    ("omlx", True, 60.0),
    ("omlx", None, 30.0),        # settings unreadable: no warning, configured value
    ("lmstudio", True, 30.0),
])
def test_review_cooldown_depends_on_omlx_cache(monkeypatch, framework, cache_on, expected):
    import backend.services as services
    monkeypatch.setattr(config, "REVIEW_COOLDOWN_SECONDS", 30.0)
    monkeypatch.setattr(config, "REVIEW_COOLDOWN_SECONDS_CACHE_ON", 60.0)
    monkeypatch.setattr(config, "get_active_framework", lambda: framework)
    monkeypatch.setattr(config, "get_omlx_cache_enabled", lambda: cache_on)
    assert services.review_cooldown_seconds() == expected
