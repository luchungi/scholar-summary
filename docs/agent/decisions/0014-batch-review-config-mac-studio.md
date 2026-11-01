# 0014: Batch review configuration on the Mac Studio (gemma-4-31B 8-bit, oMLX)

- Status: Accepted
- Date: 2026-11-01
- Context: Benchmark 2026-11-01 (0013), 6 papers of 12–38k tokens, normal conditions. All
  runs 6/6 papers with 0 retries:
  one at a time, balanced 25.4 min; two at a time, balanced 22.0 (+14%); aggressive 21.9
  (+14%); aggressive with cache off 20.7 (+19%); aggressive with chunked prefill 21.9;
  aggressive, cache off, 60k budget, 30s pause 20.2. Short papers run 25–30% faster two at
  a time; the tier and chunked prefill don't change speed. With oMLX's cache on, saving each
  prompt to SSD holds 12–20GB for 45–60s after a long review (idle peak 52–59GB vs 33GB with
  it off). Before the pause existed, this lost the next paper in every configuration,
  including one at a time.
- Decisions:
  1. oMLX: memory_guard_tier=aggressive, cache.enabled=false, chunked_prefill=false.
     Set by the user; the app warns at the start of a batch if the cache is on.
  2. .env on the Mac Studio: MAX_CONCURRENT_REVIEWS=2, REVIEW_TOKEN_BUDGET=60000,
     REVIEW_COOLDOWN_SECONDS=30. Code defaults stay 1 / 40000 / 60.
  3. With oMLX's cache on, the pause automatically rises to
     REVIEW_COOLDOWN_SECONDS_CACHE_ON (60s).
  4. CHARS_PER_TOKEN stays 3.6 although estimates run ~12% high, because it also sets
     paper truncation (GEMINI.md #13). The budget is measured in estimated tokens.
- Alternatives considered:
  - Cache on with a 60s pause: +14%, below the bar.
  - 40k budget: equal on the benchmark (one paper ran alone either way). 60k lets papers
    estimated at ~20k pair up in real batches, with the same peak (45GB, 9GB to spare).
  - The app switching the cache off itself: needs oMLX.app restarts (DE-007), and oMLX
    has no per-request cache switch.
- Consequences: Q-002, T-025, T-026.
- Revisit if: the model, quantisation or oMLX version changes, macOS's own memory use
  grows, or the cache is needed on for other uses.
