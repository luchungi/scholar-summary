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

# Ollama Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "")

# App configs
INTERESTS_FILE = os.getenv("INTERESTS_FILE", "user_interests.md")
MAX_EMAIL_FETCH = int(os.getenv("MAX_EMAIL_FETCH", "10"))
URL_RULES_PATH = os.getenv("URL_RULES_PATH", "./url/rules.json")

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
