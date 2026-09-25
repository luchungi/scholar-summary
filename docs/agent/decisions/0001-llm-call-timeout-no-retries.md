# 0001: Long timeout and no automatic retries for LLM calls

- Status: Accepted
- Date: 2026-09-25
- Context: The openai SDK (under aisuite) defaults to a 600s timeout and max_retries=2.
  qwen3.8-27b report calls with thinking ran for more than 600s. The client dropped the
  finished report and re-sent it silently (LM Studio logs 2026-08-16 and 2026-09-25 show
  a re-send exactly 600s after the first request). Up to 3 full generations, none saved.
- Decision: Configure the client with timeout≈3600s and max_retries=0. No streaming for now.
- Alternatives considered:
  - Streaming with live progress in the UI: deferred. More work, and not needed once
    retries stop.
- Consequences: A failed call surfaces once as an error instead of repeating silently. Tasks: T-001.
- Revisit if: a single report regularly takes more than 1h, or live progress is wanted.
