# 0003: Ratings as a numbered report section plus a repair call

- Status: Accepted
- Date: 2026-09-25
- Context: qwen3.8-27b leaves out the trailing <ratings> block with thinking on AND off
  (2 of 3 saved qwen reports have no ratings in the database). The "append at the very
  end" instruction is dropped after the model finishes "### 5".
- Decision: (1) Make ratings "### 6. Ratings" in the required section list, and repeat
  the requirement in the system prompt. (2) If <ratings> is still missing, make a short
  call (thinking off, temperature 0.1) that asks for only the ratings block from the report.
- Alternatives considered:
  - A stronger regex fallback for free-form "**Score: 3.0 / 5**": rejected; fragile.
- Evidence: section 6 → block present (4.0/4.5, 163s, thinking off, temperature 0.3);
  repair call → same scores in 17.5s.
- Consequences: Tasks T-003, T-004.
- Revisit if: the repair call fires often with a model (check the logs), or the scores it
  returns disagree with the report text.
