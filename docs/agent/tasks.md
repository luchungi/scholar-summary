# Tasks

## In progress

## Next

## Done (most recent first)
- [x] T-009 Add oMLX framework support alongside LM Studio with model unloading, server stopping, and auto-start on framework switch (2026-10-16, see decision 0005)
- [x] T-008 Backfill ratings for ArchAgent v2 (3.2/4.0) and Explainable MARL (1.0/4.5) reports with the repair call (2026-09-25, local data only)
- [x] T-007 Check section-6 ratings compliance for qwen at temperature 1.0, thinking on and off: both compliant without repair (2026-09-25, see 0004)
- [x] T-006 UI: thinking toggle with capability label, per-model temperature pre-filled from creator guidance, read-only top_p/top_k (2026-09-25, commit 667185a)
- [x] T-005 Backend: read creator guidance (model.yaml → generation_config.json); per-model temperature + thinking store; .env comments (2026-09-25, commit 667185a)
- [x] T-004 Ratings repair call when <ratings> is missing, used by all report paths (2026-09-25, commit 667185a)
- [x] T-003 Report prompt: make ratings "### 6. Ratings", repeat it in the system prompt (2026-09-25, commit 667185a)
- [x] T-002 Send reasoning_effort="none" on the title/relevance/repair calls; report thinking setting from .env (2026-09-25, commit 667185a)
- [x] T-001 Set timeout≈3600s and max_retries=0 on the LM Studio client in agent.py (2026-09-25, commit 667185a)
