# 0005: oMLX local framework support and framework switching

- Status: Accepted
- Date: 2026-10-16
- Context: LM Studio was the sole supported framework for hosting local LLMs.
  oMLX provides Apple Silicon native MLX inference with KV caching, OpenAI-compatible
  endpoints, and CLI/API lifecycle controls. A dual-framework architecture was requested,
  allowing seamless switching from the web UI.
- Decisions:
  1. Port Allocation: Scholar Summary remains on port 8000. oMLX is configured on port 8001
     in `~/.omlx/settings.json` and `.env` (`OMLX_BASE_URL=http://localhost:8001/v1`) to prevent
     port collision.
  2. Framework Switching Lifecycle:
     - Guard: Disabled if a paper summarization run is active (`get_active_run() is not None`).
     - Unload: Check if the current framework has a loaded model in memory (`lms ps` or oMLX
       `/v1/models/status`). If loaded, unload it before proceeding (`lms unload --all` or
       `POST /v1/models/{id}/unload`).
     - Stop: Stop the active server (`lms server stop` or `omlx stop`).
     - Switch & Auto-Start: Update active framework to the new choice in memory and `.env`
       (`LLM_FRAMEWORK=omlx` or `lmstudio`). Start the target framework server (`omlx start`
       or `lms server start`) and poll until healthy.
     - Model Detection: After start, check if any model is already loaded in the newly active
       framework. If so, display it as selected; otherwise, select "None (No Model Loaded)".
     - Progress UI: Show inline progress text and spinner in the bottom-left panel during
       the switch sequence with all controls temporarily disabled.
  3. Authentication: Auto-detect oMLX API key from `~/.omlx/settings.json`, with optional
     override via `OMLX_API_KEY` in `.env`.
  4. Inference Routing (`agent.py`): Dynamically resolves active framework, client base URL,
     API key, and model identifier (`LM_STUDIO_MODEL` vs `OMLX_MODEL`). Thinking is disabled
     for short calls via `enable_thinking=False` and `reasoning_effort="none"`.
- Consequences: Task T-009.
