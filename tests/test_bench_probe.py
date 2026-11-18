"""
Offline tests for the measurement helpers of scripts/bench_concurrency.py probe
(decision 0021). No LLM server is contacted.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("bench_concurrency", ROOT / "scripts" / "bench_concurrency.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def test_tokens_in_window_counts_inclusive_bounds():
    assert bench.tokens_in_window([0.5, 1.0, 1.5, 2.0, 2.5], 1.0, 2.0) == 3


def test_aggregate_rate_sums_streams_over_the_window():
    # Stream 1: 10 tok/s from t=0; stream 2: 5 tok/s from t=10 (its prefill ended then).
    s1 = [i / 10 for i in range(0, 400)]          # 0.0 .. 39.9
    s2 = [10 + i / 5 for i in range(0, 150)]      # 10.0 .. 39.8
    total, each = bench.aggregate_rate([s1, s2], 10.0, 30.0)
    assert each[0] == pytest.approx(10.05, abs=0.1)
    assert each[1] == pytest.approx(5.05, abs=0.1)
    assert total == pytest.approx(15.1, abs=0.2)


def test_aggregate_rate_empty_window():
    assert bench.aggregate_rate([[1.0]], 5.0, 5.0) == (None, [])


def test_release_time_finds_first_sample_back_near_baseline():
    samples = [{"mono": 100 + t, "footprint_gb": gb} for t, gb in
               [(-5, 33.0), (0, 41.0), (1, 40.5), (2, 36.0), (3, 33.8), (4, 33.2)]]
    samples.append({"mono": 99.0, "error": "status failed"})
    assert bench.release_time(samples, 100.0, 33.0) == 3.0
    assert bench.release_time(samples, 100.0, 33.0, tolerance_gb=3.5) == 2.0
    assert bench.release_time(samples, 100.0, 20.0) is None


def test_memory_summary_uses_lowest_ceiling_and_tier_threshold():
    samples = [{"footprint_gb": 40.0, "ceiling_gb": 56.0, "swap_used_gb": 0.2},
               {"footprint_gb": 44.0, "ceiling_gb": 55.0, "swap_used_gb": 0.5},
               {"error": "x"}]
    m = bench.memory_summary(samples, tier="aggressive")
    assert m["peak_footprint_gb"] == 44.0
    assert m["abort_threshold_gb"] == pytest.approx(55.0 * 0.98, abs=0.01)
    assert m["spare_gb"] == pytest.approx(55.0 * 0.98 - 44.0, abs=0.01)
    assert m["max_swap_used_gb"] == 0.5


def test_pick_pair_takes_closest_lengths():
    papers = [{"title": t, "est_tokens": n} for t, n in
              [("a", 16_643), ("b", 43_892), ("c", 17_001), ("d", 27_472), ("e", 17_353)]]
    a, b = bench.pick_pair(papers)
    assert {a["title"], b["title"]} in ({"c", "e"}, {"a", "c"})
    assert abs(a["est_tokens"] - b["est_tokens"]) == 352


class _FakeResponse:
    def __init__(self, lines):
        self.lines, self.ok, self.status_code = lines, True, 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        yield from self.lines


def _sse(obj):
    import json
    return b"data: " + json.dumps(obj).encode()


def test_stream_counts_tokens_from_logprobs_not_chunks(monkeypatch):
    """oMLX packs several tokens per chunk; each token has one logprobs entry."""
    lp = lambda n: {"content": [{"token": "x", "logprob": 0.0, "top_logprobs": []}] * n}
    lines = [b": keepalive",
             _sse({"choices": [{"delta": {"reasoning_content": "abc"}, "logprobs": lp(3)}]}),
             _sse({"choices": [{"delta": {}, "logprobs": lp(2)}]}),          # text held back by the parser
             _sse({"choices": [{"delta": {"content": "de"}, "logprobs": lp(2), "finish_reason": "length"}]}),
             _sse({"choices": [], "usage": {"completion_tokens": 7, "prompt_tokens": 10}}),
             b"data: [DONE]"]
    sent = {}

    def fake_post(url, headers=None, json=None, stream=None, timeout=None):
        sent.update(json)
        return _FakeResponse(lines)

    monkeypatch.setattr(bench.requests, "post", fake_post)

    class FakeOMLX:
        model, v1 = "m", "http://x/v1"

        def headers(self):
            return {}

    paper = {"title": "T", "url": "u", "paper_text": "body", "access_info": None}
    s = bench.Stream(FakeOMLX(), paper, "i", "n", 7)
    s.run()
    assert sent["logprobs"] is True and sent["enable_thinking"] is True
    assert len(s.token_times) == 7 == s.usage["completion_tokens"]
    assert len(s.chunk_times) == 2
    assert s.finish_reason == "length" and s.error is None and s.t_first is not None


def test_stream_falls_back_to_chunks_without_logprobs(monkeypatch):
    lines = [_sse({"choices": [{"delta": {"content": "ab"}}]}),
             _sse({"choices": [{"delta": {"content": "cd"}, "finish_reason": "stop"}]}),
             b"data: [DONE]"]
    monkeypatch.setattr(bench.requests, "post", lambda *a, **k: _FakeResponse(lines))

    class FakeOMLX:
        model, v1 = "m", "http://x/v1"

        def headers(self):
            return {}

    s = bench.Stream(FakeOMLX(), {"title": "T", "url": "u", "paper_text": "b", "access_info": None}, "i", "n", 5)
    s.run()
    assert len(s.token_times) == 2


def test_stream_sends_the_apps_review_prompt():
    import agent

    class FakeOMLX:
        model = "m"
    paper = {"title": "T", "url": "u", "paper_text": "body", "access_info": "note"}
    s = bench.Stream(FakeOMLX(), paper, "interests", "x", 1)
    expected = agent.build_report_messages("T", "u", "body", "interests", "note")
    assert s.messages[0] == expected[0]
    assert s.messages[1]["content"].endswith(expected[1]["content"].split("interests", 1)[1])
    assert "(probe x " in s.messages[1]["content"]
