# 0020: Papers a site blocks are reviewed from PDFs the user downloads, matched by DOI

- Status: Accepted
- Date: 2026-11-18
- Context: Run 146 failed 5 ACM papers (ids 423–427), all scoring 5/5 on the abstract.
  ACM is now open access, but every dl.acm.org form (/doi/, /doi/full/, /doi/pdf/) answers
  HTTP 403 with cf-mitigated: challenge ("Just a moment..."): Cloudflare's bot check,
  not a login wall. The login page sits behind the same check, so logging in from a script
  gets nowhere. The only manual path was the Dashboard upload, which made a separate
  file:// record, left the failed one in place and lost the DOI for EndNote.
- Decision: The user opens the PDF in their own browser (an "Open PDF" link on each ACM
  row, to dl.acm.org/doi/pdf/<DOI>) and saves it to Downloads. "Scan Downloads for PDFs"
  in the Failed tab reads pages 1–2 of each top-level PDF in PDF_WATCH_DIR modified in the
  last PDF_SCAN_DAYS (7) days, and matches the DOI in a failed or skipped paper's URL.
  paper_store records only the file's path in reports/user_pdfs.json; the file is never
  copied or moved. One forced run then reviews every match. Retrieval and the EndNote
  export read the PDF from that path first.
- Alternatives considered:
  - Automated ACM login, or reusing the browser's cf_clearance cookie in requests:
    rejected; it gets around the bot check (as 0019).
  - ACM text-and-data-mining access: rejected; needs an institutional agreement.
  - Background folder watcher: rejected; it would start invisible LLM runs, batch
    downloads unpredictably and add a thread. One click is cheap.
  - Copying or moving the PDF into reports/: rejected; the user keeps the file for
    EndNote, and only a path is needed.
  - Per-row "Upload PDF" with a stored copy: rejected; the browser gives bytes, not a
    path, so it would need a copy. The Dashboard upload remains for papers outside the alerts.
  - Matching by file name (ACM's <doi-suffix>.pdf): rejected; matching by the DOI in the
    text works for every publisher that prints it and cannot attach the wrong paper.
- Consequences: Tasks T-039..T-042. Papers whose URL has no DOI (ScienceDirect /pii/,
  ResearchGate) cannot match. A moved or deleted file drops back to online fetching.
- Revisit if: many failed papers lack a DOI in their URL, or ACM drops the challenge
  (then rules.json can fetch /doi/pdf/ directly).
