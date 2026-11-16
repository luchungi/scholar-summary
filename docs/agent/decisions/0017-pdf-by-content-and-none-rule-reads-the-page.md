# 0017: Recognise a PDF by its content; a "none" rule still reads the page

- Status: Accepted
- Date: 2026-11-16
- Context: 127 papers were marked failed. Replaying each through the retriever showed three
  faults. (1) For a domain marked "none", apply_rules returned None as the URL and the HTML
  fallback then fetched 'None': about 42 failures (IEEE 30, ProQuest 4, svedbergopen 4).
  (2) A PDF was recognised by Content-Type or a ".pdf" ending, so a repository
  "/bitstreams/<id>/download" PDF was scraped as HTML (1.46M characters of garbage for #98).
  (3) A "none" rule was saved whenever the LLM rule call errored, and from bot-challenge
  pages, marking the whole domain for good.
- Decision: paper_retriever fetches each URL once (_fetch) and looks for "%PDF-" in the
  first 1024 bytes. A "none" rule means "no PDF rule": the page itself is still fetched, and
  is read as a PDF if it is one. No rule is saved when the LLM call raises, and none is
  learned from a page classify_page calls blocked or failed.
- Alternatives considered:
  - Delete the existing "none" rules: not needed; they are harmless now, and T-035 reviews them.
  - Keep the HEAD request before the GET: rejected; headers are what misled the old check.
- Consequences: Task T-031. A new domain costs one GET instead of a HEAD plus a GET. A domain
  whose rule call keeps erroring asks the LLM again for every paper.
- Revisit if: one domain asks the LLM for a rule on every paper of a batch.
