# 0015: Normalise math delimiters to $ / $$ when a report is saved

- Status: Accepted
- Date: 2026-11-16
- Context: qwen3.8-27b writes \(..\) and \[..\]; the frontend's remark-math only parses
  $ and $$, and markdown eats the backslashes, so equations showed as plain text and a
  lone "=" line became a heading. All 7 qwen reports used this style, all 196 gemma math
  reports used dollars. Gemma's single-line $$x$$ (119 equations) rendered inline-sized.
- Decision: math_delimiters.normalize_math_delimiters runs in generate_paper_report after
  the ratings repair. Canonical form on disk: $x$ inline, $$ fences alone on their lines.
  Existing reports migrated with scripts/normalize_report_math.py (99 files, backups in
  reports/.math-backup-*.tar.gz).
- Alternatives considered:
  - Normalise in the frontend at render time: rejected; no JS test runner, two render
    components, and the .md files stay unreadable in other $-based viewers.
  - Make the frontend parse \( \[ natively: not possible as a setting; remark-math has no
    delimiter option and the markdown parser consumes the escapes first.
  - Add a delimiter instruction to the report prompt: rejected by the user; the
    normaliser is the guarantee and gemma's output stays untouched.
- Consequences: Tasks T-027. Thinking-on confirmed live (11 inline, 12 display fixed);
  thinking-off on oMLX was not tested, so model vs thinking is unproven but irrelevant.
- Revisit if: the renderer changes, or the "unpaired delimiter" log line starts appearing.
