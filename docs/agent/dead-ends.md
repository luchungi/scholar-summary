# Dead ends

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
