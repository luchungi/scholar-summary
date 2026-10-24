# Glossary

- **Creator guidance**: sampling values shipped with the model (hub model.yaml, else
  generation_config.json). Not LM Studio's own UI defaults, and not the user's override.
- **EndNote Import format (.enw)**: the plain-text Refer/BibIX dialect EndNote imports, one
  `%<tag> value` line per field, records separated by a blank line. Not BibTeX and not EndNote's
  own XML; it cannot carry binary data, only a path in `%>` for attachment.
- **Full paper analysis**: the generate_paper_report call. The only call the thinking
  setting applies to. Not the title, relevance filter or repair calls.
- **journal_ref**: arXiv's free-text "where this was published" field, e.g.
  "Phys. Rev. B 107, L180404 (2023)". Its presence means the preprint was published; it is not a
  clean journal name, so it is not a drop-in value for `%J`.
- **Reference type vocabulary**: the closed set of `%0` values EndNote 21's import filter
  recognises, snapshotted in url/reference_rules.json. Not a free-text label — an unrecognised
  value is silently defaulted by EndNote, not rejected.
- **Short calls**: title extraction, relevance filter, ratings repair. Always thinking off,
  temperature 0.1.
- **Thinking (reasoning) tokens**: returned by LM Studio in reasoning_content and counted in
  usage.completion_tokens_details.reasoning_tokens. Never part of message.content.
