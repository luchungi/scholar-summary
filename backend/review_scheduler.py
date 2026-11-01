"""
Token-budget scheduler for full paper reviews (docs/agent/decisions/0012).

Reviews are admitted by an estimated token budget instead of a fixed slot count:
a paper may start only if the tokens already in flight plus its own stay within
the budget, or if nothing is in flight at all. Among the waiting papers the
longest one that fits goes next, so short papers backfill around long ones.

Concurrent reviews share a prefill lock (0006.3): a review holds it until its
first token arrives, so two prompts are never prefilled at the same time.

oMLX holds 12-20 GB above the model for ~45-60s after a long review ends; a
prompt sent in that window is rejected or gets the model unloaded. So no review
starts for a cool-down after a long review finishes.

A capacity error from the LLM server (memory guard rejection or abort, busy,
overloaded) puts the paper back at the front of the queue, up to
MAX_ABORT_RETRIES times, and pauses dispatch for a retry delay. The rest of the
run drops to one review at a time only if another review was running alongside
the failed attempt; reviews already in flight keep going.

The scheduler knows nothing about the database or report files: callers pass
`review_fn` to run one review and `on_done` to record its final outcome.
"""

import bisect
import itertools
import re
import threading
import time
from contextlib import nullcontext
from typing import Any, Callable, ContextManager, Optional

import config

# Approximate tokens of system prompt, instructions and rubric that
# agent.generate_paper_report wraps around the paper text and interest profile.
PROMPT_OVERHEAD_TOKENS = 1500

# Error text that means the server refused or killed the request for capacity
# (oMLX's memory guard, LM Studio busy/overload), not a bad request.
CAPACITY_ABORT_MARKERS = (
    "memory limit exceeded", "prefill_memory_exceeded", "prefill memory guard",
    "aborted", "busy", "overload",
)
# HTTP statuses with the same meaning: 409 model busy (unload pending),
# 503 unavailable, 507 aborted before scheduling under memory pressure.
CAPACITY_STATUS_RE = re.compile(r"error code:\s*(409|503|507)\b")

MAX_ABORT_RETRIES = 2


def estimate_review_tokens(paper_text: str, user_interests: str = "") -> int:
    """Estimated context tokens of one review: prompt plus the output reserve."""
    prompt_chars = len(paper_text or "") + len(user_interests or "")
    return (int(prompt_chars / config.CHARS_PER_TOKEN) + PROMPT_OVERHEAD_TOKENS
            + config.REVIEW_OUTPUT_RESERVE_TOKENS)


def is_capacity_abort(err: BaseException) -> bool:
    s = str(err).lower()
    return any(m in s for m in CAPACITY_ABORT_MARKERS) or bool(CAPACITY_STATUS_RE.search(s))


class _Entry:
    __slots__ = ("item", "tokens", "label", "retries", "key", "overlapped")

    def __init__(self, item: Any, tokens: int, label: str, seq: int):
        self.item = item
        self.tokens = tokens
        self.label = label
        self.retries = 0
        # Set when another review ran alongside the current attempt.
        self.overlapped = False
        # Normal papers sort longest first, ties in submission order.
        self.key = (1, -tokens, seq)


class ReviewScheduler:
    """
    review_fn(item, tag, on_first_token) -> result
        Runs one review. Must call on_first_token() when prefill finishes;
        any exception counts as a failed attempt.
    on_done(item, tag, result, error)
        Called exactly once per item with its final outcome (error is None on
        success). Not called for an attempt that is being retried.
    """

    def __init__(
        self,
        review_fn: Callable[[Any, str, Callable[[], None]], Any],
        on_done: Callable[[Any, str, Any, Optional[BaseException]], None],
        max_concurrency: int,
        token_budget: int,
        thread_context: Callable[[], ContextManager] = nullcontext,
        log: Callable[[str], None] = print,
        cooldown_tokens: Optional[int] = None,
        cooldown_seconds: Optional[float] = None,
        retry_delay_seconds: Optional[float] = None,
    ):
        self._review_fn = review_fn
        self._on_done = on_done
        self._max_concurrency = max(1, max_concurrency)
        self._token_budget = token_budget
        self._thread_context = thread_context
        self._log = log
        self._cooldown_tokens = (config.REVIEW_COOLDOWN_TOKENS
                                 if cooldown_tokens is None else cooldown_tokens)
        self._cooldown_seconds = (config.REVIEW_COOLDOWN_SECONDS
                                  if cooldown_seconds is None else cooldown_seconds)
        self._retry_delay = (config.REVIEW_RETRY_DELAY_SECONDS
                             if retry_delay_seconds is None else retry_delay_seconds)

        self._cond = threading.Condition()
        self._prefill_lock = threading.Lock()
        self._pending: list = []          # sorted by _Entry.key
        self._running: set = set()
        self._seq = itertools.count()
        self._front_seq = itertools.count()
        self._active = 0
        self._in_flight_tokens = 0
        self._free_slots = list(range(1, self._max_concurrency + 1))
        self._not_before = 0.0            # monotonic time before which nothing starts
        self._closed = False
        self._threads: list = []
        self.abort_retries = 0
        self.peak_concurrency = 0

    def submit(self, item: Any, tokens: int, label: str = "") -> None:
        """Queue a paper for review. Thread-safe; may be called while run() is going."""
        with self._cond:
            if self._closed:
                raise RuntimeError("ReviewScheduler.submit() after close()")
            entry = _Entry(item, tokens, label, next(self._seq))
            self._insert(entry)
            self._cond.notify_all()

    def close(self) -> None:
        """No more submissions: run() returns once the queue drains."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def run(self) -> None:
        """Dispatch reviews until close() has been called and every review has finished."""
        with self._cond:
            while True:
                if self._closed and not self._pending and self._active == 0:
                    break
                wait_for = self._not_before - time.monotonic()
                if wait_for > 0 and self._pending:
                    self._cond.wait(timeout=wait_for)
                    continue
                entry = self._pick()
                if entry is not None:
                    self._start(entry)
                    continue
                self._cond.wait()
        for t in self._threads:
            t.join()

    # ------------------------------------------------------------------
    # Internals; _insert/_pick/_start/_pause are called with self._cond held.
    # ------------------------------------------------------------------

    def _insert(self, entry: _Entry) -> None:
        keys = [e.key for e in self._pending]
        self._pending.insert(bisect.bisect(keys, entry.key), entry)

    def _pick(self) -> Optional[_Entry]:
        if not self._pending or self._active >= self._max_concurrency:
            return None
        if self._active == 0:
            # Nothing in flight: the head runs even if it alone exceeds the budget.
            return self._pending.pop(0)
        for i, entry in enumerate(self._pending):
            if self._in_flight_tokens + entry.tokens <= self._token_budget:
                return self._pending.pop(i)
        return None

    def _start(self, entry: _Entry) -> None:
        self._active += 1
        self._in_flight_tokens += entry.tokens
        self.peak_concurrency = max(self.peak_concurrency, self._active)
        entry.overlapped = False
        self._running.add(entry)
        if len(self._running) > 1:
            for e in self._running:
                e.overlapped = True
        slot = self._free_slots.pop(0)
        t = threading.Thread(
            target=self._worker, args=(entry, slot),
            name=f"ReviewWorker-{slot}", daemon=True,
        )
        self._threads.append(t)
        t.start()

    def _pause(self, seconds: float) -> None:
        self._not_before = max(self._not_before, time.monotonic() + seconds)

    def _worker(self, entry: _Entry, slot: int) -> None:
        retry = False
        try:
            with self._thread_context():
                tag = f"[Slot {slot}: {entry.label}]"
                self._log(f"\n{tag} (~{entry.tokens} tokens) Waiting for prefill lock...")
                self._prefill_lock.acquire()
                released = False

                def on_first_token():
                    nonlocal released
                    if not released:
                        released = True
                        self._prefill_lock.release()
                        self._log(f"{tag} [+] Prefill completed; first token received. Prefill lock released.")

                result, error = None, None
                try:
                    result = self._review_fn(entry.item, tag, on_first_token)
                except Exception as e:
                    error = e
                finally:
                    if not released:
                        released = True
                        self._prefill_lock.release()

                retry = (error is not None and is_capacity_abort(error)
                         and entry.retries < MAX_ABORT_RETRIES)
                if retry:
                    self._log(f"{tag} [!] Server refused or aborted the review for capacity: {error}")
                    self._log(f"{tag} [!] Retry {entry.retries + 1}/{MAX_ABORT_RETRIES} after "
                              f"{self._retry_delay:.0f}s"
                              + ("; the rest of the batch runs one review at a time."
                                 if entry.overlapped else "."))
                else:
                    try:
                        self._on_done(entry.item, tag, result, error)
                    except Exception as e:
                        self._log(f"{tag} [-] Error recording review outcome: {e}")
                if entry.tokens >= self._cooldown_tokens and not retry:
                    self._log(f"{tag} [*] Long review finished; waiting {self._cooldown_seconds:.0f}s "
                              f"for the LLM server's memory to settle before the next prefill.")
        finally:
            with self._cond:
                self._active -= 1
                self._in_flight_tokens -= entry.tokens
                self._running.discard(entry)
                bisect.insort(self._free_slots, slot)
                if entry.tokens >= self._cooldown_tokens:
                    self._pause(self._cooldown_seconds)
                if retry:
                    entry.retries += 1
                    self.abort_retries += 1
                    if entry.overlapped:
                        self._max_concurrency = 1
                    self._pause(self._retry_delay)
                    entry.key = (0, next(self._front_seq), 0)
                    self._insert(entry)
                self._cond.notify_all()
