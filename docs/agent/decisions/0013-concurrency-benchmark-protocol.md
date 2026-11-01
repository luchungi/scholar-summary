# 0013: Concurrency benchmark protocol

- Status: Accepted
- Date: 2026-11-01
- Context: 0012's defaults and the oMLX settings had to be measured under normal conditions
  (VS Code closed, Safari only); a Claude/VS Code session understates the memory headroom.
- Decisions:
  1. scripts/bench_concurrency.py: `prepare` caches 6 already-reviewed papers (4 short,
     1 mid, 1 long) under bench/ (gitignored); `run` reviews them through the app's
     ReviewScheduler with thinking off, started from Terminal under caffeinate.
  2. The script runs its own server. For each configuration it writes ~/.omlx/settings.json,
     frees port 8001 (terminating a leftover process if needed), starts `omlx serve` as a
     child, and confirms a new process ID and the expected "Memory guard tier" before
     timing anything. Unconfirmed configurations are SKIPPED. Settings are restored at the
     end, ctrl-C included.
  3. A per-configuration line placed before the paper text stops oMLX reusing its prompt
     cache across configurations.
  4. It records total time, per-paper prefill and total time, retries, server aborts, oMLX
     memory, ceiling and swap, and estimated vs actual tokens.
  5. Acceptance: ≥15% faster than one at a time, with zero lost papers. Retries are
     reported separately.
- Alternatives considered:
  - Restarting through oMLX.app (`omlx restart`): silently kept the old server (DE-007).
  - Benchmarking from this session: VS Code's memory understates the headroom.
- Consequences: T-023, T-024. Rerun the script after any model change.
