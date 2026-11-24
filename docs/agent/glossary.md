# Glossary

- **Abstract-only paper**: a paper whose link gave a landing page (an abstract, menus) and no
  full text. Gated on the abstract, then recorded as failed or skipped; never reviewed (0018).
- **ADS identifier (bibcode)**: the 19-character record ID in a NASA ADS URL, e.g.
  2026arXiv261041855S. For arXiv records it embeds the arXiv ID. Not a DOI.
- **Backend**: the FastAPI process on port 8000. Not the LLM server (LM Studio, or oMLX on
  8001) — "stop server" and "shut down backend" are different operations on different
  processes.
- **Bot-challenge page**: what a site sends instead of the paper when it suspects a script
  ("Just a moment...", a CAPTCHA), sometimes with HTTP 200. Not paper text, and not a paywall.
- **Canonical math form**: $x$ inline and $$ fences alone on their own lines, the only form
  the frontend renders as intended. Not \(..\) / \[..\], and not single-line $$x$$.
- **Capacity error**: the LLM server refusing or killing a request for memory or load (oMLX
  prefill memory guard, memory-limit abort, HTTP 409/503/507, busy). Retried by the
  scheduler. Not a bad request or a network error.
- **Cited result**: a web result whose [W1] marker appears in the finished report's text. It
  shows the model used the result, not that the result improved the review (0022).
- **Cool-down**: the pause after a review whose estimated prompt (output reserve excluded) is
  ≥30k tokens, before the next prefill starts, so oMLX's memory can settle (0021). Not the
  retry delay after a capacity error.
- **Coverage**: how much of a paper retrieve_paper got: full, abstract, blocked or failed.
  Only full is reviewed. Not the same as source (pdf or html): a long HTML page is full.
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
- **"none" rule**: a domain's entry in url/rules.json saying no rule leads to its PDFs. The
  page itself is still read (0017). Not "skip this domain", and not proof of a paywall.
- **Normal conditions**: how batches run in practice: VS Code closed, only Safari (the app UI)
  open. Benchmarks must match this; runs from a Claude/VS Code session don't.
- **OpenReview challenge**: the HTTP 403 ChallengeRequiredError OpenReview gives logged-out
  requests on its site and API; a logged-in request passes (0023). Not a 403 for a private paper.
- **Output reserve**: the output tokens the token budget counts per review (15k with thinking
  on, 2k off), added to the prompt estimate. Bookkeeping only; it does not limit generation.
- **Prompt cache (oMLX)**: oMLX's store of computed keys and values (KV cache) for prompt
  prefixes, in memory and on SSD, reused by a later request with the same start. Not the
  generated text. Skipped per request with X-oMLX-Cache-Store: off (0021).
- **Reference type vocabulary**: the closed set of `%0` values EndNote 21's import filter
  recognises, snapshotted in url/reference_rules.json. Not a free-text label — an unrecognised
  value is silently defaulted by EndNote, not rejected.
- **Search decision**: the short thinking-off call that may request web searches before a
  review. It sees the paper but not the profile. Not the review call, which has no tools (0022).
- **Short calls**: title extraction, relevance filter, ratings repair, search decision. Always
  thinking off, temperature 0.1.
- **Teardown**: unload the active framework's resident model, then stop that framework's
  server. Shared by the framework switch (0005) and backend shutdown (0011). Does not
  include killing the backend process.
- **Thinking (reasoning) tokens**: returned by LM Studio in reasoning_content and counted in
  usage.completion_tokens_details.reasoning_tokens. Never part of message.content.
- **Token budget**: the cap on estimated tokens across reviews in flight (prompt + output
  reserve) that decides whether another review may start. Not a slot count.
- **User PDF**: a PDF the user saved for a failed paper, recorded in reports/user_pdfs.json
  by path only. Not an uploaded file: the Dashboard upload makes its own record, and the app
  keeps no copy of a user PDF.
- **Web Sources**: the report section the app builds from cited Tavily results, placed before
  Ratings. Not written by the model, and not a list of every result returned (0022).
