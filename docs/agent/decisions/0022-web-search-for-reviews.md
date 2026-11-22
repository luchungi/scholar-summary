# 0022: Model-decided web search for reviews, with the local API locked down

- Status: Accepted
- Date: 2026-11-22
- Context: Reviews relied on the paper and the model's own knowledge. Tavily gives 1,000
  credits a month; the app is on pace for ~75 reviews a month. aisuite drops `tools` unless
  its non-streaming loop runs, which would hold the prefill lock through generation. An audit
  found any website could use the local API and that reports loaded remote images. Trial
  2026-11-22 (4 papers, Qwen3.8 thinking on, oMLX 0.8.2): all searched, 10 credits, decision
  plus search ~10% of review compute, 6.7 GB minimum available, no capacity retries.
- Decisions:
  1. One `web_search` tool over Tavily's REST API: basic depth, 5 results, 1 credit a query.
  2. A short thinking-off call sees the paper, not the interest profile, and may request up to
     3 searches in one round. The review call has no tools. Capacity retries reuse the results.
  3. Search may inform literature, background and missing metadata (Section 5 only). Background
     may inform the quality score; citation counts, reputation or opinions of the paper may not.
  4. The key lives only in ~/.config/scholar-summary/tavily_key (600, folder 700), read at search
     time. Never in Keychain, .env, the environment, logs, prompts or error text.
  5. Searching stops at 800 credits per UTC month, reserved atomically. Any search failure
     leaves the review running without search.
  6. Queries: one line, ≤200 chars, no URLs or emails. Results are cleaned, labelled untrusted
     and never fetched. Reports keep no images and link only the paper and returned sources;
     the app builds Web Sources, and [W1]-marked metadata never reaches EndNote.
  7. The API accepts only the app's origins, checks Host and Sec-Fetch-Site, and sends a CSP.
  8. reports/web_search_log.jsonl records queries, results and citations per review;
     scripts/web_search_summary.py summarises them.
- Alternatives considered:
  - Tavily MCP: a layer for one tool, exposes tools costing up to 250 credits; its URL auth
    puts the key in the URL and its local launch runs unpinned `@latest` code.
  - macOS Keychain: rejected by the user; the app must have no route into Keychain.
  - .env: mode 644, and its values reach the lms and omlx child processes.
  - Tool in the review call: may waste long thinking before a search, then repeat it.
  - Two rounds or an open loop: more prefill, credits and scheduler memory risk.
  - No search on uploads: unnecessary, the user does not upload working papers.
- Consequences: T-046..T-049, Q-005. A citation shows use, not that the review improved.
- Revisit if: T-048 shows little useful citation, credits near the cap, or the model, oMLX tool
  parsing or Tavily's pricing changes.
