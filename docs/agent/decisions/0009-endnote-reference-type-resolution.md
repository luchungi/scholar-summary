# 0009: EndNote reference type resolution from metadata, not venue

- Status: Accepted
- Date: 2026-10-24
- Context: arXiv preprints imported into EndNote 21 as "Book". Root cause found by dumping
  EndNote's own type list from `/Applications/EndNote 21/Filters/EndNote Import.enf` and the
  type table in `EndNote.pdf`: "Preprint" (`citation_service.py:270`, commit 6abd1f0) is NOT in
  EndNote 21's reference type vocabulary, so the import filter silently substitutes its own
  default. See DE-003. Second bug found in the same pass: the Crossref mapping
  (`citation_service.py:210`) was binary — `journal-article` else "Conference Proceedings" — so
  `posted-content`, `dissertation`, `book-chapter` and `report` all became Conference Proceedings.
- Decision:
  1. Derive `%0` from already-resolved metadata (arXiv-ness, Crossref `type`, journal_ref
     presence), not from the host. Default "Journal Article".
  2. Validate every `%0` against a closed vocabulary snapshot of EndNote 21's type list. On a
     miss: substitute the default and log a warning naming the rejected value.
  3. Config in `url/reference_rules.json`: `endnote_types`, `default_type`, `crossref_type_map`,
     `host_overrides` (host-keyed, for the cases the APIs get wrong: openreview.net → Conference
     Paper, thesis repositories → Thesis), `preprint_venues`, `periodical_types`,
     `secondary_title_types`. Host lookup strips `www.` and walks up to parent domains, so
     `search.proquest.com` matches a `proquest.com` entry.
  4. A Crossref type wins over a host override: the Crossref type describes the specific work,
     an override is only a venue-wide guess.
  5. arXiv preprints → "Journal Article" (matches Google Scholar's own .enw, keeping the library
     internally consistent). `proceedings-article` → "Conference Paper", not "Conference
     Proceedings" (that type means the whole volume, not a paper in it).
  6. `resolve_paper_metadata` now has a single exit point. The previous early `return`s in tiers
     1 and 2 bypassed the final sanity checks, so validation could not be added at the end.
- Alternatives considered:
  - Host-keyed rules.json mirroring `url/rules.json`: rejected; of 298 papers in the database
    arxiv.org has 124 and ~55 hosts have 1-2 each, so the tail needs permanent hand-maintenance,
    and it discards structured type data the APIs already return.
  - Folding a `reference` block into `url/rules.json`: rejected; couples PDF-URL rewriting with
    citation semantics in a file that is currently only about PDF resolution.
  - Code-only constants, no JSON: rejected; every venue correction becomes a code edit.
  - Parsing the vocabulary out of `EndNote Import.enf` at runtime so custom EndNote types are
    picked up automatically: rejected; undocumented binary format and a fixed install path, would
    break on an EndNote upgrade.
  - Silent fallback without a warning: rejected; that is the failure mode that let "Preprint"
    ship unnoticed.
- Consequences: Tasks T-013, T-014. Adding a venue is a JSON edit. Previously exported records
  are not corrected (forward-only: EndNote's Refer import has no upsert, so re-importing
  duplicates rather than updates; cleanup inside EndNote is Reference > Change Reference Type).
- Revisit if: a custom reference type is added inside EndNote (then update the `endnote_types`
  snapshot), or EndNote changes its default type list.
