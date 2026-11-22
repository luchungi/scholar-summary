# Open questions

- Q-001 (2026-10-27) Can LM Studio hold a model in memory after `lms server stop`, and
  does `lms ps` still report it? Verified with both servers off: `lms ps` returns cleanly
  in ~0.1s (no hang, no error) and oMLX's HTTP unload fails closed to "No model loaded",
  so teardown degrades gracefully either way (0011.7). What is still untested is the case
  that matters — a model actually resident with the API server stopped. If `lms ps` goes
  blind there, a shutdown could leave the model in RAM silently.
  Needs: load a model in LM Studio, `lms server stop`, then check `lms ps` and
  `lms unload --all`. If it goes blind, teardown should stop the server after unloading
  only, and never the reverse order.

- Q-003 (2026-11-16) Is 12,000 characters the right line between a landing page and a full
  paper served as HTML (HTML_FULLTEXT_MIN_CHARS, 0018)? Landing pages seen so far ran
  1.7k–8.8k characters; a paywalled page with a long reference list could pass.
  Needs: check the Source line of the next reports that say "HTML scrape".

- Q-004 (2026-11-16) Why did 20 papers that extract fine today (7 arXiv, 13 direct PDFs)
  fail before 2026-11-01? Reasons were not stored then (T-021 added them). Leaning: the
  report stage, not retrieval. Needs: nothing unless new failures show a pattern.

- Q-005 (2026-11-22) Are Gemma-era ratings comparable with Qwen-era ones? Paper 415 scored
  relevance 5.0 on Gemma without thinking, and 2.0–3.0 across five Qwen reviews with thinking,
  with and without search. Reports do not store their model. Leaning: do not compare across the
  switch (around 2026-11-16). Needs: re-review a small Gemma-era sample, or store the model per report.
