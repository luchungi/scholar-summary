# Dead ends

## DE-003: "%0 Preprint" as the reference type for arXiv papers (2026-10-24, commit 6abd1f0)
- Hypothesis: EndNote 21 has a Preprint reference type, so `%0 Preprint` files arXiv papers correctly.
- What was tried: citation_service.py:270 set ref_type="Preprint" for every arXiv result.
- Result: EndNote imported them as "Book". Dumping the type list from
  /Applications/EndNote 21/Filters/EndNote Import.enf and the type table in EndNote.pdf
  confirms "Preprint" is absent from the vocabulary; the import filter falls back to its own default.
- Why it failed: an unrecognised %0 value is not an error in EndNote, it is silently defaulted.
- Do NOT retry unless: a "Preprint" type is added manually inside EndNote AND the endnote_types
  snapshot in url/reference_rules.json is updated to match (see 0009).

## DE-004: "%<" as a PDF attachment tag (2026-10-24, commit 0110e84, decision 0008)
- Hypothesis: writing both "%< path" and "%> path" makes EndNote bind the PDF more reliably.
- What was tried: generate_enw_content / generate_combined_enw emitted both tags with the
  absolute staged PDF path.
- Result: attachment worked, but through %> alone; %< put the filesystem path into the Research
  Notes field of every imported record. EndNote 21's tag table is explicit:
  "%>File Attachments  %<Research Notes".
- Why it failed: %< was assumed to be an attachment variant; it is an unrelated text field.
- Do NOT retry unless: never. %> is the only attachment tag.

## DE-001: Turning off qwen3.8 thinking through LM Studio's OpenAI API, other ways (2026-09-25)
- Hypothesis: common thinking-off switches work in LM Studio.
- What was tried (qwen3.8-27b, LM Studio, "Is 91 prime?" prompt):
  extra_body chat_template_kwargs.enable_thinking=false → 62 thinking tokens;
  extra_body reasoning.effort="none" → 41; "/no_think" in the prompt → 117 (more than baseline).
- Result: all ignored. Only the top-level reasoning_effort="none" gave 0 thinking tokens.
- Do NOT retry unless: LM Studio documents support for these, or another backend is used.

## DE-002: Ratings block as an "append at the very end" instruction after the section list (2026-09-25)
- Hypothesis: an IMPORTANT instruction after the section list makes models append <ratings>.
- What was tried: the prompt used through commit c43fd19; qwen3.8-27b with thinking on and off.
- Result: block missing in both test runs and in 2 of 3 saved qwen reports; gemma complied.
- Why it failed (best guess): the model treats the last numbered section as the end.
- Do NOT retry unless: never; use a numbered section (see 0003).
