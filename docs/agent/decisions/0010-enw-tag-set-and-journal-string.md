# 0010: .enw tag set and the arXiv journal string

- Status: Accepted
- Date: 2026-10-24
- Context: Three field-level problems in the .enw output. (a) `%J` carried only "arXiv preprint"
  with no identifier. (b) The abstract (`%X`) is never read in EndNote and bloats the file.
  (c) The PDF path appeared in the Research Notes field: EndNote 21's tag table reads
  `%^Caption  %>File Attachments  %<Research Notes  %[Access Date`, so the `%<` tag written per
  decision 0008 was never an attachment tag (DE-004). Also `%J` and `%B` were emitted with the
  same value, though the tag table defines `%J` = Journal Name and `%B` = Secondary Title (of a
  Book or Conference Name).
- Decision:
  1. `%J` for an unpublished arXiv preprint becomes `arXiv preprint arXiv:{id}` with the version
     suffix retained, e.g. `arXiv preprint arXiv:2605.15156v2`. The version is read from the Atom
     response's `<id>` element, which is always versioned; it must NOT come from the input URL,
     because 0 of 128 arXiv URLs in the database carry a version (Scholar alerts link to bare
     `/abs/` or `/pdf/` paths). A bare `id_list` query returns the latest version, so the recorded
     version is the revision whose PDF was downloaded.
  2. Non-arXiv preprints use the same mechanism via `preprint_venues` journal templates keyed by
     host, with the DOI as identifier (e.g. `Research Square preprint {doi}`), falling back to
     just the venue label when no identifier is available.
  3. When arXiv returns both a journal_ref and a DOI, do not return early from the arXiv tier —
     chain to Crossref for structured journal/volume/issue/pages. arXiv's journal_ref is free text
     that mashes fields together (`Phys. Rev. B 107, L180404 (2023)`) and produces a dirty journal
     name. The early return is why published arXiv papers never reached the Crossref tier of
     0007's waterfall.
  4. Drop `%X` entirely. `abstract` is still resolved: it is used by the relevance pre-filter
     (`config.py`) and arrives free in the same API responses.
  5. Drop `%<` entirely. `%>` alone performs the attachment.
  6. Emit `%J` only for periodical types and `%B` only for conference papers and book sections,
     never both. Driven by `secondary_title_types` in `url/reference_rules.json`.
- Alternatives considered:
  - Stripping the arXiv version (Google Scholar's convention): rejected in favour of recording
    which revision was reviewed and downloaded.
  - Taking the version from the input URL: rejected; 0 of 128 arXiv URLs in the database carry
    one, so it would be indistinguishable from stripping, and inconsistent if a versioned URL
    were ever pasted manually.
  - Using journal_ref raw, or regex-parsing it: rejected; raw is a dirty composite that breaks
    author-date styles and the journal term list, and journal_ref has no standard format across
    arXiv so a parser is fragile.
  - An `enw_fields` toggle for the abstract: rejected; indirection for a preference unlikely to be
    flipped back, and restoring the three lines is trivial.
  - Putting the quality/relevance ratings, or a path to the generated markdown report, into `%<`:
    rejected as scope creep that re-occupies the field being cleared.
- Consequences: Task T-013. Supersedes decision 1 of 0008 (the `%<` attachment tag). Verified
  live against both APIs: a bare `/pdf/2605.15156` URL now exports `%J arXiv preprint
  arXiv:2605.15156v2`, and a published preprint exports `%J Physical Review B` with `%V`/`%N`
  from Crossref instead of the free-text journal_ref.
- Revisit if: EndNote changes its tag table, or abstracts start being read inside EndNote.
