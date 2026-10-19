# 0007: EndNote Citation (.enw) and PDF Export Automation

- Status: Accepted
- Date: 2026-10-19
- Context: After analyzing Google Scholar alerts, moving papers into reference management (EndNote) previously
  required manually navigating to Google Scholar for an `.enw` file and to publisher sites for the PDF.
  Automating direct Google Scholar citation scraping risks aggressive bot blocks and IP CAPTCHAs.
  Additionally, storing all downloaded PDFs permanently on disk would cause unnecessary local disk growth.
- Decisions:
  1. Trigger & UX: On-demand export via the web interface. On report detail pages (`ReportDetail.tsx`), three
     export options are offered: `Download .enw`, `Download PDF`, and `Export Both` (triggers two direct browser downloads).
     On the reports feed (`ReportsFeed.tsx`), multi-selection checkboxes allow selecting multiple reports and downloading
     a single bundled ZIP archive containing individual PDFs, individual `.enw` files, and a master `citations_all.enw`
     file that imports all references into EndNote in a single double-click.
  2. Delivery: Browser downloads directly into the user's `~/Downloads` directory, integrating cleanly with desktop EndNote.
  3. Metadata Resolution Engine: Multi-tier waterfall avoiding direct Google Scholar scraping:
     - Tier 1: arXiv Atom API for arXiv preprints (extracts full authors, publication date, abstract, doi).
     - Tier 2: Crossref REST API for DOIs (extracts authors, journal, year, volume, issue, page, doi, abstract).
     - Tier 3: Local report parser fallback (`extract_metadata_from_report` parses report markdown).
     - Tier 4: HTML citation meta tags (`<meta name="citation_*">`) fallback.
  4. On-Demand PDF Streaming: PDFs are not stored permanently on disk. When requested, `backend/pdf_service.py`
     resolves the direct PDF URL (arXiv direct link, academic API, or domain rules in `url/rules.json`) and streams
     chunks directly to the browser.
  5. Academic Standard Naming: Filenames are consistently formatted as `{Author}_{Year}_{ShortTitle}.enw` and `.pdf`
     (e.g., `Wiese_2026_GROMM_Generative_Risk_neutral_Option_Market.enw`).
- Consequences: Task T-011. Eliminates manual citation search and PDF retrieval while keeping zero local PDF storage overhead.
