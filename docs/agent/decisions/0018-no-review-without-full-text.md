# 0018: A paper without full text is never reviewed; the relevance gate reads the abstract

- Status: Accepted
- Date: 2026-11-16
- Context: The first paper from a paywalled domain used to be reviewed from its landing
  page. 15 saved reports came from such pages; their quality ratings sat at 1.0–3.0 whatever
  the paper, and 5 were written from 21–505 characters of bot-challenge text. This replaces
  the "HTML fallback is reviewed" part of GEMINI.md decision 15(b).
- Decision: retrieve_paper always returns a dict with "coverage": full, abstract, blocked
  or failed. A non-PDF page is "full" only at config.HTML_FULLTEXT_MIN_CHARS (12000)
  characters or more. Only "full" is reviewed. For the rest services.decide_unreviewable runs
  the relevance gate on the abstract (page metadata, IEEE's embedded JSON, or an academic
  API) and records the paper as failed, with the reason, the score and "Upload the PDF to
  review it.", or as skipped when the score is under the threshold. A manual retry (force)
  is never skipped. With no abstract the paper is failed with the reason alone.
- Alternatives considered:
  - Abstract-only reports labelled as such: rejected; ratings from an abstract mean nothing.
  - Mark as failed without the gate: rejected; the score is what says whether the PDF is
    worth fetching by hand.
- Consequences: Task T-032. Paywalled papers count as failures in a run's totals. Papers
  124, 132, 231, 358, 414 and 375 were set to failed by hand; the 10 other landing-page
  reports were left as they are.
- Revisit if: paywalled pages with long reference lists pass as full text, or short real
  papers served as HTML are classed as abstracts (Q-003).
