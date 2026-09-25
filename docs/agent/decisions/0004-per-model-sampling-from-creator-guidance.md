# 0004: Per-model report temperature, defaulting to the creators' recommendation

- Status: Accepted
- Date: 2026-09-25
- Context: The report ran at a global temperature of 0.3. The creators ship recommendations
  locally: ~/.lmstudio/hub/models/<key>/model.yaml (temperature, top_p, top_k, the
  reasoning flag), with generation_config.json in the model folder as a fallback.
  Qwen3.8: 1.0 / 0.95 / 20. Gemma 4: 1.0 / 0.95 / 64.
- Decision: The report temperature defaults to the creators' value and is stored per model.
  When a model loads, the UI fills in the creators' value unless the user has overridden
  it for that model. The UI shows the creators' temperature/top_p/top_k as guidance
  (top_p/top_k read-only, not sent). .env gets comments quoting the recommendations.
  The short calls stay at a fixed 0.1.
- Alternatives considered:
  - Our own 0.3 with thinking off / 0.6 with it on: rejected in favour of the creators'
    values (0.6 was outdated Qwen3 guidance).
  - top_p/top_k as settings: rejected; LM Studio already applies the creators' values.
- Consequences: Tasks T-005, T-006. T-007 verified qwen3.8 at 1.0 still writes section 6
  itself (thinking off: 159s, 4.0/4.5; thinking on: 746s, 6,425 thinking tokens, 3.5/4.5).
- Revisit if: ratings/format compliance drops noticeably at the creators' temperature.
