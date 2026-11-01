# 0012: Token-budget review scheduling with pipelined triage

- Status: Accepted
- Date: 2026-11-01
- Context: Run 126 (2026-10-31, oMLX, gemma-4-31B 8-bit, 0006's fixed 2 slots) lost 2 of 8
  papers to oMLX memory aborts and ran slower than one at a time. 0006's sizing was wrong:
  the weights are 33GB, not 19.5, and attention memory is ~160KB/token, not 13.1GB per 48k.
  The limit is oMLX's dynamic ceiling, which depends on paper length, not slot count.
- Decisions:
  1. A review starts only if the estimated tokens in flight (prompt + 2k output reserve)
     stay within REVIEW_TOKEN_BUDGET. With nothing in flight the head of the queue always
     runs; otherwise the longest waiting paper that fits goes next. MAX_CONCURRENT_REVIEWS
     caps the count (code default 1). The prefill lock (0006.3) is kept.
  2. Triage feeds the scheduler as papers pass (supersedes 0006.2): TRIAGE_CONCURRENCY=4
     download and relevance-check in parallel.
  3. After a review of REVIEW_COOLDOWN_TOKENS (30k estimated) or more, nothing starts for
     REVIEW_COOLDOWN_SECONDS.
  4. Capacity errors (prefill memory guard, memory-limit abort, HTTP 409/503/507,
     busy/overload) put the paper back at the front, up to 2 retries, each after
     REVIEW_RETRY_DELAY_SECONDS (60s). The run drops to one at a time only if another
     review overlapped the failed attempt (supersedes 0006.4). A final failure's reason is
     stored in skip_reason and shown in the Failed tab.
  5. oMLX is external: the app reads ~/.omlx/settings.json but never writes it.
  6. url/rules.json writes re-read the file under a lock and replace it atomically,
     because triage now runs in parallel.
- Alternatives considered:
  - Fixed slot count from RAM (0006.1): ignores paper length (DE-005).
  - Wait for all of triage, then sort: the GPU sits idle ~10s per paper during triage.
  - Strict longest-first: short papers would wait behind a long one that runs alone anyway.
  - Pairs scheduling: tried, slower (DE-006).
- Consequences: T-018..T-023. Only the writing half gets faster; prefill is compute-bound.
- Revisit if: the model, quantisation or framework changes.
