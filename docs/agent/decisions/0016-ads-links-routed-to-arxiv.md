# 0016: Resolve NASA ADS links through arXiv, not the ADS page or API

- Status: Accepted
- Date: 2026-11-16
- Context: ui.adsabs.harvard.edu/abs/... returns HTTP 405 with an AWS WAF CAPTCHA; all 5
  ADS papers in the database had failed. All 5 were arXiv records, and the ADS identifier
  embeds the arXiv ID (2026arXiv261041855S -> 2610.41855).
- Decision: academic_api.extract_arxiv_id decodes ADS arXiv identifiers, so those papers
  take the existing arXiv path with no request to ADS. Other ADS records ask the link
  gateway (/link_gateway/<id>/EPRINT_PDF) and follow its redirect only to arxiv.org. If
  the arXiv API is down, an ADS link still returns the direct arXiv PDF URL.
- Alternatives considered:
  - ADS API (api.adsabs.harvard.edu/v1): rejected for now; needs a personal token and
    no journal-only ADS record has appeared yet.
  - A regex_replace rule in url/rules.json: rejected; would not reach the PDF download
    and EndNote paths, which share extract_arxiv_id.
- Consequences: Task T-028. PDF download and EndNote export also work for ADS arXiv links.
  The gateway is on the CAPTCHA'd domain and could be blocked later.
- Revisit if: the gateway starts returning the CAPTCHA, or ADS records with no arXiv
  e-print start failing (then add the token-based API).
