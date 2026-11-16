# 0019: Papers blocked by bot protection: arXiv copy by title, otherwise a clear reason

- Status: Accepted
- Date: 2026-11-16
- Context: About 50 failed papers sit behind bot protection (HTTP 403/405/429 or a
  JavaScript challenge): ScienceDirect 12, ResearchGate 8, ACM 8, OpenReview 7, IGI 6,
  Springer 4. OpenReview now challenges its API as well. Of 64 such papers checked, 2 had
  an arXiv copy under the same title.
- Decision: when the link does not give the paper, academic_api.find_arxiv_by_title searches
  arXiv (all main title words, then any of them; one request per 3 s) and accepts a hit only
  if titles_match: similarity ≥ 0.92 on letters and digits, exact for titles under 30 such
  characters. The clean title from an API or the page is preferred to the alert's. The
  report's Source line says the text is the arXiv copy. Otherwise the paper is recorded as
  "Blocked by the site's bot protection (...)" and handled per 0018.
- Alternatives considered:
  - A real browser (Playwright, possibly with the institutional login): rejected; heavy,
    fragile, and it deliberately gets around the sites' bot checks.
  - Browser TLS-fingerprint impersonation (curl_cffi): not tested; the session's permission
    system refused the test as unauthorised access. Rejected on the same grounds.
  - Semantic Scholar title search: its keyless API answered 429.
  - OpenAlex and Crossref PDF links: see DE-008.
- Consequences: Tasks T-033, T-034. Each paper without full text costs up to two arXiv
  requests. arXiv answered 429 after about 60 searches in five minutes during the probe.
- Revisit if: arXiv title searches return 429 in normal batches, or relevant blocked
  papers pile up in the Failed tab faster than manual upload can clear them.
