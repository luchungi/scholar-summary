# 0021: Four reviews at once on Qwen3.8-27B, thinking-aware reserve, cache-store header

- Status: Accepted
- Date: 2026-11-18
- Context: The model changed to Qwen3.8-27B 8-bit (hybrid: 16 of 64 layers full attention,
  ~64KB/token cache vs gemma's ~160KB) with thinking on (9-13k output tokens, ~85-90% of a
  review is generation). 0014 was validated on gemma with thinking off. Probe 2026-11-18
  (scripts/bench_concurrency.py probe, normal conditions): generation 16.1 / 29.4 / 41.2 /
  51.7 tok/s combined for 1-4 reviews (+82%, +40%, +26%), peak 38GB, 14.4GB spare at N=4.
  Two prompts sent together: oMLX processes them one after the other anyway (101.5s vs
  101.5s). Memory is back 1.2s after a review ends; a 39k prompt 5s later ran fine.
  oMLX 0.7.3 honours X-oMLX-Cache-Store: off per request (skips the cache save).
- Decisions:
  1. .env: MAX_CONCURRENT_REVIEWS=4, REVIEW_TOKEN_BUDGET=140000, REVIEW_COOLDOWN_SECONDS=5.
  2. Output reserve: 15k tokens when the active model thinks, 2k otherwise. Bookkeeping
     only, never limits generation. The pause compares the prompt estimate only.
  3. The prefill lock (0006.3) stays.
  4. The app sends X-oMLX-Cache-Store: off on every oMLX request; oMLX's cache stays on for
     other uses. The 60s cache-on pause and warning apply only to oMLX < 0.7.3 or unknown.
  5. Acceptance rule for N: >= 15% more combined tok/s than N-1 and >= 6GB spare.
- Alternatives considered:
  - Full makespan benchmark (0013) with thinking on: 5+ hours; generation dominates, so
    combined tok/s predicts batch time.
  - Keep the 2k reserve and only raise the budget: budget stops reflecting memory.
  - Cap generation at 15k tokens: would truncate reviews (13.2k seen).
  - Cache off globally (0014.1): loses prefix reuse for normal LLM use.
  - Concurrent prompt processing: no gain (stage A), loses the app's control of order.
- Consequences: Supersedes 0014 for this model; Q-002 obsolete. T-043, T-044, T-045.
  Real reviews reach ~33k tokens each, so expect ~9-10GB spare, not 14.4.
- Revisit if: the model, quantisation, thinking setting or oMLX version changes, or a
  capacity retry appears in a batch log.
