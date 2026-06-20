# Scholar Summary Agent

An autonomous prototype AI agent built using `aisuite` that retrieves Google Alerts from your Gmail account, extracts paper texts (supporting direct HTML scraping and PDF parsing), analyzes them using a locally hosted LLM in LM Studio, and maintains/refines your researcher interests profile dynamically based on your feedback.

## Features

- **Gmail API Fetching**: Searches for alert emails sent by `scholaralerts-noreply@google.com`.
- **Paper Retrieval**: Follows redirects, converts arXiv abstract links to PDF downloads, reads PDFs using `pypdf`, and parses standard HTML web pages by stripping non-article content.
- **Local LLM Summarization**: Uses `aisuite` to interface with your LM Studio local server.
- **Interest Profile Refinement**: Compares the generated report to your interest profile ([user_interests.md](user_interests.md)), captures your feedback, uses the LLM to refine your interests.
- **Flexible Modes**: Run the Gmail loop, or analyze a single paper URL directly.

---

## File Structure

- [main.py](main.py): CLI orchestrator and entry point.
- [agent.py](agent.py): Wrapper for local LLM requests using `aisuite`.
- [gmail_fetcher.py](gmail_fetcher.py): Handles Gmail API queries and extracts links.
- [paper_retriever.py](paper_retriever.py): Fetches pages and extracts text (HTML or PDF).
- [config.py](config.py): Environment configuration loader.
- [user_interests.md](user_interests.md): The Markdown-based researcher interest profile.
- [.env](.env): Reference configuration template.

---

## Prerequisites & Setup

### 1. Python Environment

Ensure you have virtual environments managed by `uv`. The project packages can be synchronized or executed using:

```bash
uv sync
```

### 2. Configure LM Studio (or similar alternatives e.g. Ollama)

1. Open **LM Studio**.
2. Download/Load your preferred model (e.g., `Qwen-2.5-7B-Instruct` or `Llama-3.1-8B-Instruct`).
3. Navigate to the **Local Server** tab (server icon on the left panel).
4. Click **Start Server** (listening on `http://localhost:1234/v1` by default).
5. Copy the exact loaded **model identifier** (e.g., `qwen2.5-7b-instruct`).

### 3. Set up Google Mail API Credentials

The agent uses the Gmail API (OAuth2) for secure email access:
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Search for and enable the **Gmail API** for your project.
4. Set up the **OAuth consent screen** (User Type: External, Publishing status: Testing is fine. Be sure to add your email address to the **Test Users** list).
5. Navigate to **Credentials** -> **Create Credentials** -> **OAuth client ID**.
6. Select application type **Desktop app**, name it (e.g., "Scholar Summary Agent"), and click **Create**.
7. Download the client secrets JSON file, rename it to `credentials.json`, and place it in the directory set up in .env.
8. First authentication via browser then save token.json in the directory set up in .env

### 4. Create your Environment File

Set up configuration:
1. Gmail json path
2. LM Studio url and model (key can be anything)
3. Application settings such as path to user interest file, max emails to process, path to reports.

---

## Usage

### Run Interactive Menu

Start the interactive CLI menu:

```bash
uv run python main.py
```

### Process Gmail Alerts Directly

Skip the menu and run the Gmail fetcher loop immediately:

```bash
uv run python main.py --gmail
```

### Test a Specific Paper URL

Test the text retriever, summarizer, and profile feedback flow on a specific paper URL (e.g., arXiv or a web page) without using Gmail:

```bash
uv run python main.py --url https://arxiv.org/abs/2304.00001
```

# Web UI Version

Run a web UI (100% Gemini built) that does the same as above but keeps track of all analysis and allow easy loading of models with LM Studio.

```bash
uv run python run_web.py
```