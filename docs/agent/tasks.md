# Tasks

## In progress

## Next
- [ ] T-015 Manual check in EndNote 21: import one batch and confirm %> alone still binds the
      PDF, the reference type reads Journal Article, and Research Notes is empty (see 0010)
- [ ] T-017 Reconcile stale "running" run rows on startup, for the crash and ctrl-C paths
      T-016 does not cover (rejected as 0011's primary mechanism, see its alternatives)

## Done (most recent first)
- [x] T-016 Backend shutdown teardown: shared FrameworkManager.stream_teardown consumed by
      both the switch and shutdown paths, GET /api/shutdown/teardown/stream, ShutdownTerminal.tsx,
      active-run marking, status-poll teardown; tests/test_shutdown_teardown.py (9 tests)
      (2026-10-27, see 0011)
- [x] T-013 Fix EndNote export: metadata-derived validated reference types with
      url/reference_rules.json, arXiv journal string with the version from the Atom <id>,
      Crossref chaining for published preprints, dropped %X and %<, split %J/%B
      (2026-10-24, see decisions 0009 and 0010)
- [x] T-014 Add pytest as a dev dependency and tests/test_citation_service.py: 32 tests over
      the type resolver, the valid-EndNote-type invariant and golden .enw output
      (2026-10-24, see 0009)
- [x] T-012 Implement 1-Click EndNote Batch Export with attached PDFs, local staging directory, pre-flight paywall check, and direct macOS integration (2026-10-20, see decision 0008)
- [x] T-011 Automate EndNote citation (.enw) and PDF downloads with multi-source metadata resolution, on-demand streaming, and bulk ZIP export (2026-10-19)
- [x] T-010 Implement batch paper reviews with hardware-aware concurrency, two-phase pipeline, and staggered prefill (2026-10-18, see decision 0006)
- [x] T-009 Add oMLX framework support alongside LM Studio with model unloading, server stopping, and auto-start on framework switch (2026-10-16, see decision 0005)
- [x] T-008 Backfill ratings for ArchAgent v2 (3.2/4.0) and Explainable MARL (1.0/4.5) reports with the repair call (2026-09-25, local data only)
- [x] T-007 Check section-6 ratings compliance for qwen at temperature 1.0, thinking on and off: both compliant without repair (2026-09-25, see 0004)
- [x] T-006 UI: thinking toggle with capability label, per-model temperature pre-filled from creator guidance, read-only top_p/top_k (2026-09-25, commit 667185a)
- [x] T-005 Backend: read creator guidance (model.yaml → generation_config.json); per-model temperature + thinking store; .env comments (2026-09-25, commit 667185a)
- [x] T-004 Ratings repair call when <ratings> is missing, used by all report paths (2026-09-25, commit 667185a)
- [x] T-003 Report prompt: make ratings "### 6. Ratings", repeat it in the system prompt (2026-09-25, commit 667185a)
- [x] T-002 Send reasoning_effort="none" on the title/relevance/repair calls; report thinking setting from .env (2026-09-25, commit 667185a)
- [x] T-001 Set timeout≈3600s and max_retries=0 on the LM Studio client in agent.py (2026-09-25, commit 667185a)
