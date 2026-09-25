# Glossary

- **Creator guidance**: sampling values shipped with the model (hub model.yaml, else
  generation_config.json). Not LM Studio's own UI defaults, and not the user's override.
- **Full paper analysis**: the generate_paper_report call. The only call the thinking
  setting applies to. Not the title, relevance filter or repair calls.
- **Short calls**: title extraction, relevance filter, ratings repair. Always thinking off,
  temperature 0.1.
- **Thinking (reasoning) tokens**: returned by LM Studio in reasoning_content and counted in
  usage.completion_tokens_details.reasoning_tokens. Never part of message.content.
