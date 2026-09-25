import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# Gmail API Configuration
GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
GMAIL_TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "token.json")

# LM Studio Configuration
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "openai:qwen2.5-7b-instruct")
LM_STUDIO_API_KEY = os.getenv("LM_STUDIO_API_KEY", "lm-studio")

# App configs
INTERESTS_FILE = os.getenv("INTERESTS_FILE", "user_interests.md")
MAX_EMAIL_FETCH = int(os.getenv("MAX_EMAIL_FETCH", "10"))
URL_RULES_PATH = os.getenv("URL_RULES_PATH", "./url/rules.json")

# LLM prompt budget & sampling
# Paper text budget: sized for ~25 dense pages (excl. references) inside a 64k context,
# leaving ~16k tokens for the interest profile, instructions, and the generated report.
MAX_PAPER_TOKENS = int(os.getenv("MAX_PAPER_TOKENS", "48000"))
CHARS_PER_TOKEN = float(os.getenv("CHARS_PER_TOKEN", "3.6"))
MAX_PAPER_CHARS = int(MAX_PAPER_TOKENS * CHARS_PER_TOKEN)
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# Relevance pre-filter gate: skip full analysis when a quick title+abstract check
# scores below the threshold. Set RELEVANCE_GATE_ENABLED=false to disable.
RELEVANCE_GATE_ENABLED = os.getenv("RELEVANCE_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
RELEVANCE_GATE_THRESHOLD = float(os.getenv("RELEVANCE_GATE_THRESHOLD", "2.5"))

# Report Settings
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")
FAILED_PAPERS_FILE = os.getenv("FAILED_PAPERS_FILE", "failed_papers.md")

def validate_config():
    """Validates configuration. Returns True if valid, raises ValueError if missing credentials."""
    credentials_file = Path(GMAIL_CREDENTIALS_PATH)
    if not credentials_file.exists():
        raise ValueError(
            f"Gmail API credentials file not found at '{GMAIL_CREDENTIALS_PATH}'.\n"
            f"Please download your OAuth client credentials JSON file from the Google Cloud Console, "
            f"save it as '{GMAIL_CREDENTIALS_PATH}' in the root directory, or configure GMAIL_CREDENTIALS_PATH."
        )
    return True
