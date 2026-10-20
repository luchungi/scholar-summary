# 0008: 1-Click EndNote Batch Export with Attached PDFs

- Status: Accepted
- Date: 2026-10-20
- Context: A standard `.enw` file is plain text and cannot embed binary PDFs inside itself. Previously, downloading a ZIP required unzipping, and double-clicking `citations_all.enw` imported references without any attached PDFs because the `.enw` lacked attachment tags (`%<` and `%>`).
- Decisions:
  1. Attachment Tag Mapping: `generate_enw_content` and `generate_combined_enw` now support `pdf_local_path` and write `%< <path>` and `%> <path>` tags, which EndNote uses to automatically copy and bind PDFs into its active library (`.Data/PDF/`).
  2. Local-First 1-Click Workflow (`POST /api/reports/endnote-export`): Downloads the selected batch of PDFs into a dedicated timestamped folder (`~/Downloads/EndNote_Imports/Batch_YYYYMMDD_HHMMSS/` or `Single_...`), generates consolidated `citations_all.enw` with absolute paths, and triggers macOS `open -a "EndNote 21"` to automatically ingest all references with PDFs in a single click.
  3. Pre-Flight Paywall Check (`POST /api/reports/export-preflight`):
     - Fast-Path: If 100% of selected papers have downloadable PDFs, exports immediately with zero friction.
     - Confirmation Modal: If any paper is paywalled or HTML-only, displays a prompt listing the affected papers with options to "Export All (Citation-Only for paywalled)" or "Export Only Papers with PDFs".
  4. Finder Integration (`POST /api/reports/reveal-in-finder`): Post-export toast provides a "Reveal in Finder" button to inspect the staged directory.
  5. UI Updates:
     - Reports Feed: Primary button is "Export to EndNote (1-Click)"; secondary button retains "Download ZIP".
     - Report Detail: "Export Both" is upgraded to the 1-click "Export to EndNote" action.
- Consequences: Task T-012. Users can import complete batches of papers and their full-text PDFs into EndNote 21 with a single click.
