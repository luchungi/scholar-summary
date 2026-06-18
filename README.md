# scholar-summary

A minimal agent that:

1. finds Google Scholar alert emails in Gmail,
2. prompts a locally hosted LLM to analyze each paper,
3. generates a report that includes:
   - high-level key ideas,
   - links to related literature and contribution,
   - fit with user interests.

## Usage

Set environment variables:

- `GMAIL_USERNAME`
- `GMAIL_APP_PASSWORD` (Gmail app password)
- `USER_INTEREST_PROMPTS` (separate prompts with `||`)
- `LOCAL_LLM_ENDPOINT` (optional, default `http://localhost:11434/v1/chat/completions`)
- `LOCAL_LLM_MODEL` (optional, default `llama3.1`)

Then run:

```bash
python scholar_alert_agent.py
```
