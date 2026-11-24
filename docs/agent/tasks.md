# Tasks

## In progress

## Next
- [ ] T-015 Manual check in EndNote 21: import one batch and confirm %> alone still binds the
      PDF, the reference type reads Journal Article, and Research Notes is empty (see 0010)
- [ ] T-017 Reconcile stale "running" run rows on startup, for the crash and ctrl-C paths
      T-016 does not cover (rejected as 0011's primary mechanism, see its alternatives)
- [ ] T-025 Compare gemma-4-31B 4-bit vs 8-bit review quality on 3–4 already-reviewed papers
- [ ] T-029 Restart the app, then retry from the Failed tab the papers that now give full
      text: the 5 ADS ones (ids 36, 102, 189, 192, 416; see 0016) and ids 12, 16, 20, 22, 29,
      30, 34, 41, 68, 69, 83, 98, 107, 117, 121, 122, 156, 212, 251, 270, 275, 280, 282, 305,
      348, 350 (user; see 0017, 0019)
- [ ] T-035 Read <meta name="citation_pdf_url"> before asking the LLM for a PDF rule, and
      review the existing "none" rules in url/rules.json (svedbergopen.com is OJS; see 0017)
- [ ] T-036 One URL can hold a failed and a skipped record at once (a failed paper later
      skipped by the gate, or the reverse); make the two exclusive
- [ ] T-037 Look at the markdown table styling in the browser (index.css; not checked by eye)
- [ ] T-038 extract_doi_from_url keeps Emerald's trailing article number
      (10.1108/MBE-08-2025-0176/1385260), so Crossref finds no title or abstract
- [ ] T-040 Match downloaded PDFs to failed papers without a DOI in their URL by the
      normalised title (≥ 30 chars) on page 1 (see 0020)
- [ ] T-041 Check the Failed tab's "Scan Downloads for PDFs" and "Open PDF" buttons in the
      browser, and change UPLOAD_HINT to point at the scan (see 0020)
- [ ] T-042 Download and scan ACM papers 423–426 (user; see 0020)
- [ ] T-044 Watch the first 2-3 batches at N=4 for "Retry"/capacity lines and oMLX's peak;
      on any capacity retry, drop to N=3 with REVIEW_TOKEN_BUDGET=105000 (see 0021)
- [ ] T-048 Around 2026-12-22, review the web search log: search rate, credits, cited results
      and weak domains; decide whether to keep, filter or remove search (see 0022)
- [ ] T-049 Confirm four reviews truly overlap on oMLX 0.8.2 with shorter papers; the 0022 trial
      reached three because of the token budget (see 0021, 0022, T-044)
- [ ] T-052 Retry OpenReview papers 49, 68, 72, 204, 330, 334, 446 from the Failed tab, then
      import one through the one-click EndNote export, which was only tested with stubs (user; see 0023)

## Done (most recent first)
- [x] T-051 Single-PDF and EndNote exports fetch OpenReview PDFs through the API; single and
      bulk export of paper 446 checked live (2026-11-24, commit ebf0559, see 0023)
- [x] T-050 OpenReview API client, private login file, setup script and retrieval order; 343
      tests; paper 446 retrieved live, V1 checked on an ICLR 2021 paper (2026-11-24, commit ebf0559, see 0023)
- [x] T-047 Local API guard (Origin, Host, Sec-Fetch-Site), restricted CORS, CSP, no report
      images, link allowlist; checked in headless Chrome on both ports (2026-11-22, commit ec15de1, see 0022)
- [x] T-046 Model-decided Tavily search, private key file, credit cap, Web Sources, usefulness
      log and summary script; 288 tests, 4-paper live trial and control (2026-11-22, commit ec15de1, see 0022)
- [x] T-043 oMLX prompt cache back on; 48 GB of incompatible old cache blocks deleted
      (user, 2026-11-18, see 0021)
- [x] T-045 Thinking-aware output reserve (15k), pause on prompt estimate, X-oMLX-Cache-Store
      header with oMLX version check, `probe` subcommand; 202 tests (2026-11-18, commit 3f2009e, see 0021)
- [x] T-026 oMLX memory_guard_tier=aggressive and cache.enabled=false set (confirmed from the
      settings backup 2026-11-18; followed by T-043, see 0021)
- [x] T-039 Scan Downloads for PDFs of failed papers, matched by DOI; paper_store, Open PDF
      link for ACM; tests/test_paper_store.py (8 tests); #427 reviewed live (2026-11-18, see 0020)
- [x] T-034 Alert titles keep the spaces around Scholar's bold keywords (gmail_fetcher);
      tests/test_gmail_fetcher.py (4 tests) (2026-11-16, see 0019)
- [x] T-033 arXiv copy by title when the link gives no paper: find_arxiv_by_title, throttled,
      near-exact title match; tests/test_academic_api.py (+11 tests) (2026-11-16, see 0019)
- [x] T-032 No review without full text: coverage in retrieve_paper, bot-challenge and
      abstract detection, decide_unreviewable in triage; 6 bad records set to failed
      (2026-11-16, see 0018)
- [x] T-031 Retrieval fixes: PDF recognised by content, "none" rule still reads the page, no
      rule saved on an LLM error; tests/test_paper_retriever.py (26 tests) (2026-11-16, see 0017)
- [x] T-030 remark-gfm 4.0.1 (single-tilde strikethrough off) in ReportDetail and InterestTab,
      table CSS; 136 saved table rows checked, none with a pipe inside math (2026-11-16)
- [x] T-028 Route NASA ADS links to arXiv: identifier decoding in extract_arxiv_id, link
      gateway fallback; tests/test_academic_api.py (26 tests) (2026-11-16, see 0016)
- [x] T-027 Normalise report math to $ / $$ at save: math_delimiters.py, call in
      generate_paper_report, scripts/normalize_report_math.py, 99 reports migrated;
      tests/test_math_delimiters.py (30 tests) (2026-11-16, see 0015)
- [x] T-024 Benchmark run and analysed under normal conditions; final configuration in 0014 (2026-11-01)
- [x] T-023 scripts/bench_concurrency.py: own `omlx serve`, confirmed restarts, memory sampling (2026-11-01, see 0013)
- [x] T-022 Token usage and prefill/generation timing logged on streamed reports (2026-11-01)
- [x] T-021 Capacity-error retries (2, 60s), drop to one at a time only on overlap, failure reasons in the UI (2026-11-01, see 0012)
- [x] T-020 Token-budget admission with longest-fit backfill and a pause after long reviews (2026-11-01, see 0012, 0014)
