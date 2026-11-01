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

- Q-002 (2026-11-01) Is the 60k budget safe for the largest pairs it allows (~52k actual tokens
  combined)? The benchmark's largest pair was ~37k actual tokens at a 45GB peak (9GB to spare);
  estimated +2.5GB more. Needs: watch the first real batches' logs for "Retry" or capacity
  lines; if any appear, lower REVIEW_TOKEN_BUDGET to 50000.
