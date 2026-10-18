# 0006: Hardware-aware batch paper reviews with two-phase pipeline and staggered prefill

- Status: Accepted
- Date: 2026-10-18
- Context: Paper reviews were previously executed strictly one at a time. For batches of alert papers,
  evaluating whether batch processing is feasible required balancing inference throughput against unified
  memory limits on Apple Silicon (Mac Studio M4 Max 64GB vs M1 Mac 16GB). Sizing calculations showed that
  running 2 full reviews (each up to 48k tokens context) on 27B-31B models consumes ~53 GB of unified memory
  (model weights ~19.5 GB + 2 x 13.1 GB KV cache + ~7.5 GB system overhead). A batch size of 3 would require
  >66 GB and trigger catastrophic SSD swapping. On 16GB M1 Mac, concurrency must remain 1.
- Decisions:
  1. Concurrency Cap: Configured via `MAX_CONCURRENT_REVIEWS` in `.env`, auto-defaulting to 2 on >=48GB RAM
     (Mac Studio M4 Max) and 1 on <48GB RAM (M1 Mac) via `sysctl hw.memsize` detection.
  2. Two-Phase Pipeline:
     - Phase 1 (Rapid Triage): Sequentially prefetch texts and execute the lightweight relevance gate
       (`assess_relevance`, thinking off, ~800 tokens) across all candidate papers. Eliminates 40-70% of off-profile
       papers before allocating heavy review slots.
     - Phase 2 (Bounded Review Pool): Passing papers are dispatched into a bounded worker pool of up to
       `MAX_CONCURRENT_REVIEWS` parallel slots.
  3. Staggered Prefill Barrier: Concurrent workers share a `prefill_lock`. Worker 1 acquires the lock during
     prompt evaluation (~48k tokens) and releases it immediately upon receiving its Time-To-First-Token (via
     `on_first_token` streaming callback in `agent.generate_paper_report`). Worker 2 then begins prefilling while
     Worker 1 performs memory-bandwidth-bound token decoding. This ensures peak activation memory during prompt
     evaluation never overlaps.
  4. Graceful Degradation: If the local server (LM Studio or oMLX) rejects slot 2 or encounters slot/busy errors,
     the paper is re-queued and concurrency throttles to 1 for the remainder of the run.
  5. Thread-Safe Logging & Database: Worker stdout is routed to the run SSE queue via `LogCapture(q)` with slot
     tags (`[Slot N: <Title>]`), SQLite WAL mode is enabled on connection with 30s busy timeout, and DB commits
     are guarded by `_db_write_lock`.
- Consequences: Task T-010.
