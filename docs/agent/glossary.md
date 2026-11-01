# Glossary

- **Backend**: the FastAPI process on port 8000. Not the LLM server (LM Studio, or oMLX on
  8001) — "stop server" and "shut down backend" are different operations on different
  processes.
- **Capacity error**: the LLM server refusing or killing a request for memory or load (oMLX
  prefill memory guard, memory-limit abort, HTTP 409/503/507, busy). Retried by the
  scheduler. Not a bad request or a network error.
- **Cool-down**: the pause after a long review (≥30k estimated tokens) before the next prefill
  starts, so oMLX's memory can settle. Not the retry delay after a capacity error.
- **Creator guidance**: sampling values shipped with the model (hub model.yaml, else
  generation_config.json). Not LM Studio's own UI defaults, and not the user's override.
- **Dynamic ceiling (oMLX)**: the live memory limit oMLX enforces on itself, from free and
  inactive RAM, part of other apps' memory, and the tier's reserve; it aborts at 95%
  (balanced) or 98% (aggressive). Not iogpu.wired_limit_mb, which caps only GPU-locked memory.
- **EndNote Import format (.enw)**: the plain-text Refer/BibIX dialect EndNote imports, one
  `%<tag> value` line per field, records separated by a blank line. Not BibTeX and not EndNote's
  own XML; it cannot carry binary data, only a path in `%>` for attachment.
- **Full paper analysis**: the generate_paper_report call. The only call the thinking
  setting applies to. Not the title, relevance filter or repair calls.
- **journal_ref**: arXiv's free-text "where this was published" field, e.g.
  "Phys. Rev. B 107, L180404 (2023)". Its presence means the preprint was published; it is not a
  clean journal name, so it is not a drop-in value for `%J`.
- **Normal conditions**: how batches run in practice: VS Code closed, only Safari (the app UI)
  open. Benchmarks must match this; runs from a Claude/VS Code session don't.
- **Reference type vocabulary**: the closed set of `%0` values EndNote 21's import filter
  recognises, snapshotted in url/reference_rules.json. Not a free-text label — an unrecognised
  value is silently defaulted by EndNote, not rejected.
- **Short calls**: title extraction, relevance filter, ratings repair. Always thinking off,
  temperature 0.1.
- **Teardown**: unload the active framework's resident model, then stop that framework's
  server. Shared by the framework switch (0005) and backend shutdown (0011). Does not
  include killing the backend process.
- **Thinking (reasoning) tokens**: returned by LM Studio in reasoning_content and counted in
  usage.completion_tokens_details.reasoning_tokens. Never part of message.content.
- **Token budget**: the cap on estimated tokens across reviews in flight (prompt + output
  reserve) that decides whether another review may start. Not a slot count.
