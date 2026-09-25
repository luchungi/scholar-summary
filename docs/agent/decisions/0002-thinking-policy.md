# 0002: Thinking only for the full paper analysis, off for short calls

- Status: Accepted
- Date: 2026-09-25
- Context: Measured on 2609.24972v2.pdf with qwen3.8-27b: 454s and 6,347 tokens (2,769
  thinking) with thinking on, 140s and 1,428 tokens with it off. LM Studio has
  separateReasoningContentInAPI=true, so thinking text never leaks into message.content
  (the original "we extract the thinking instead of the answer" hypothesis was disproved).
- Decision: The title, relevance filter and ratings repair calls always send
  reasoning_effort="none". The full analysis uses a thinking on/off setting: default in
  .env, overridable in the UI. The UI always shows the toggle and labels it "supports
  thinking" when hub model.yaml says reasoning: true, "unknown" otherwise.
- Alternatives considered:
  - Thinking off everywhere / on with a token budget: rejected. Keeping thinking optional
    for the report lets its value be compared.
  - Sending reasoning_effort only to models that can think: unnecessary. LM Studio ignores
    it for gemma-4-26b-a4b.
  - Hiding the toggle for models flagged as unable to think: rejected. The metadata is
    unreliable (the gemma MoE has no model.yaml but its chat template mentions thinking).
- Consequences: Tasks T-002, T-005.
- Revisit if: LM Studio changes how reasoning_effort works, or a non-LM-Studio backend is added.
