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
