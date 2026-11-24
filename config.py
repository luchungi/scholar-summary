import json
import os
import re
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

# LLM Framework Selection: 'lmstudio' or 'omlx'
LLM_FRAMEWORK = os.getenv("LLM_FRAMEWORK", "lmstudio").lower()

# LM Studio Configuration
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "openai:")
LM_STUDIO_API_KEY = os.getenv("LM_STUDIO_API_KEY", "lm-studio")

# oMLX Configuration
def get_omlx_api_key() -> str:
    env_key = os.getenv("OMLX_API_KEY")
    if env_key:
        return env_key
    settings_path = Path.home() / ".omlx" / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            return data.get("auth", {}).get("api_key", "")
        except Exception:
            pass
    return ""

def get_omlx_cache_enabled():
    """oMLX's global prompt-cache setting (read only), or None if it can't be read."""
    settings_path = Path.home() / ".omlx" / "settings.json"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        return bool(data.get("cache", {}).get("enabled", True))
    except Exception:
        return None

# Sent on every app request to oMLX: keeps the request out of oMLX's prompt cache, so the
# cache can stay on for other uses without its 12-20 GB save spike after each review.
# oMLX reads it from 0.7.3; older versions ignore it (decision 0021).
OMLX_CACHE_STORE_HEADERS = {"X-oMLX-Cache-Store": "off"}
OMLX_CACHE_STORE_HEADER_MIN_VERSION = (0, 7, 3)

def version_at_least(version, minimum) -> bool:
    """True if a dotted version string such as '0.7.3' is >= the minimum tuple."""
    if not version:
        return False
    parts = [int(x) for x in re.findall(r"\d+", str(version))[:len(minimum)]]
    if not parts:
        return False
    return tuple(parts + [0] * (len(minimum) - len(parts))) >= tuple(minimum)

OMLX_BASE_URL = os.getenv("OMLX_BASE_URL", "http://localhost:8001/v1")
OMLX_MODEL = os.getenv("OMLX_MODEL", "openai:")
OMLX_API_KEY = get_omlx_api_key()

def get_active_framework() -> str:
    global LLM_FRAMEWORK
    return LLM_FRAMEWORK

def get_active_base_url() -> str:
    if get_active_framework() == "omlx":
        return OMLX_BASE_URL
    return LM_STUDIO_BASE_URL

def get_active_model() -> str:
    if get_active_framework() == "omlx":
        return OMLX_MODEL
    return LM_STUDIO_MODEL

def get_active_api_key() -> str:
    if get_active_framework() == "omlx":
        global OMLX_API_KEY
        if not OMLX_API_KEY:
            OMLX_API_KEY = get_omlx_api_key()
        return OMLX_API_KEY
    return LM_STUDIO_API_KEY

def set_active_framework(framework: str):
    global LLM_FRAMEWORK
    LLM_FRAMEWORK = framework.lower()

def set_active_model(model_key: str):
    global LM_STUDIO_MODEL, OMLX_MODEL
    formatted = f"openai:{model_key}" if model_key and not model_key.startswith("openai:") else model_key
    if get_active_framework() == "omlx":
        OMLX_MODEL = formatted
    else:
        LM_STUDIO_MODEL = formatted

# App configs
INTERESTS_FILE = os.getenv("INTERESTS_FILE", "user_interests.md")
MAX_EMAIL_FETCH = int(os.getenv("MAX_EMAIL_FETCH", "10"))
URL_RULES_PATH = os.getenv("URL_RULES_PATH", "./url/rules.json")
# EndNote reference type vocabulary, Crossref type map, host overrides and preprint
# journal templates used when writing .enw files (see docs/agent/decisions/0009, 0010).
REFERENCE_RULES_PATH = os.getenv("REFERENCE_RULES_PATH", "./url/reference_rules.json")

# LLM prompt budget & sampling
# Paper text budget: sized for ~25 dense pages (excl. references) inside a 64k context,
# leaving ~16k tokens for the interest profile, instructions, and the generated report.
MAX_PAPER_TOKENS = int(os.getenv("MAX_PAPER_TOKENS", "48000"))
CHARS_PER_TOKEN = float(os.getenv("CHARS_PER_TOKEN", "3.6"))
MAX_PAPER_CHARS = int(MAX_PAPER_TOKENS * CHARS_PER_TOKEN)

# A page that is not a PDF counts as the paper itself only with at least this much text.
# Shorter pages are landing pages (an abstract, menus): they are not reviewed, see
# services.decide_unreviewable.
HTML_FULLTEXT_MIN_CHARS = int(os.getenv("HTML_FULLTEXT_MIN_CHARS", "12000"))

# LLM call behaviour (docs/agent/decisions/0001, 0002, 0004)
# Local generation with thinking can exceed the openai SDK's 600s default; a timeout there
# silently re-sent the whole request, so calls get a long timeout and no automatic retries.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "3600"))
# Short calls (title extraction, relevance gate, ratings repair, profile update, PDF rules)
# always run with thinking off at this fixed temperature.
SHORT_CALL_TEMPERATURE = float(os.getenv("SHORT_CALL_TEMPERATURE", "0.1"))
# Full paper analysis: default thinking on/off; overridable per model from the UI.
REPORT_THINKING = os.getenv("REPORT_THINKING", "false").lower() in ("1", "true", "yes", "on")
# Full paper analysis: fallback temperature, used only when there is no per-model UI override
# and no creator guidance for the model (LM Studio model.yaml / generation_config.json).
REPORT_TEMPERATURE = float(os.getenv("REPORT_TEMPERATURE", os.getenv("LLM_TEMPERATURE", "0.3")))
# Per-model UI overrides (temperature, thinking) for the full paper analysis.
MODEL_SETTINGS_PATH = os.getenv("MODEL_SETTINGS_PATH", "model_settings.json")

# Relevance pre-filter gate: skip full analysis when a quick title+abstract check
# scores below the threshold. Set RELEVANCE_GATE_ENABLED=false to disable.
RELEVANCE_GATE_ENABLED = os.getenv("RELEVANCE_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
RELEVANCE_GATE_THRESHOLD = float(os.getenv("RELEVANCE_GATE_THRESHOLD", "2.5"))

# Concurrency & Batch Settings (docs/agent/decisions/0006, 0012)
def get_system_ram_gb() -> float:
    """Returns detected system RAM in GB, or a safe default of 16.0."""
    try:
        import subprocess
        res = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip().isdigit():
            return int(res.stdout.strip()) / (1024 ** 3)
    except Exception:
        pass
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        pass
    return 16.0

def get_default_max_concurrency() -> int:
    # One review at a time until the concurrency benchmark (T-024) shows a win:
    # fixed 2 slots on the 64GB Mac ran slower and lost papers to oMLX memory aborts
    # (0012.1, DE-005). Set MAX_CONCURRENT_REVIEWS to opt in.
    return 1

MAX_CONCURRENT_REVIEWS = int(os.getenv("MAX_CONCURRENT_REVIEWS", str(get_default_max_concurrency())))

def get_max_concurrent_reviews() -> int:
    env_val = os.getenv("MAX_CONCURRENT_REVIEWS")
    if env_val and env_val.isdigit():
        return int(env_val)
    return MAX_CONCURRENT_REVIEWS

# Reviews are admitted while the estimated tokens in flight (prompt + output reserve)
# stay within this budget; a paper over budget on its own runs alone (0012.2).
REVIEW_TOKEN_BUDGET = int(os.getenv("REVIEW_TOKEN_BUDGET", "40000"))
REVIEW_OUTPUT_RESERVE_TOKENS = int(os.getenv("REVIEW_OUTPUT_RESERVE_TOKENS", "2000"))
# With thinking on, reviews write 9-13k tokens (Qwen3.8-27B, 2026-11-18), so the budget
# counts this many output tokens per review instead. It never limits generation.
REVIEW_OUTPUT_RESERVE_TOKENS_THINKING = int(os.getenv("REVIEW_OUTPUT_RESERVE_TOKENS_THINKING", "15000"))
# oMLX holds 12-20 GB above the model for ~45-60s after a long review ends, and rejects
# or unloads on a prompt sent in that window: pause dispatch after reviews whose
# estimated prompt (output reserve excluded) is this long.
REVIEW_COOLDOWN_TOKENS = int(os.getenv("REVIEW_COOLDOWN_TOKENS", "30000"))
REVIEW_COOLDOWN_SECONDS = float(os.getenv("REVIEW_COOLDOWN_SECONDS", "60"))
# The spike comes from oMLX saving the prompt cache to SSD and takes 45-60s to settle;
# with oMLX's cache on, the cool-down never drops below this (decision 0014).
REVIEW_COOLDOWN_SECONDS_CACHE_ON = float(os.getenv("REVIEW_COOLDOWN_SECONDS_CACHE_ON", "60"))
# Wait before retrying a review the server refused or aborted for capacity.
REVIEW_RETRY_DELAY_SECONDS = float(os.getenv("REVIEW_RETRY_DELAY_SECONDS", "60"))
# Papers fetched and relevance-gated in parallel during triage (0012.3).
TRIAGE_CONCURRENCY = int(os.getenv("TRIAGE_CONCURRENCY", "4"))

# Report Settings
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")
FAILED_PAPERS_FILE = os.getenv("FAILED_PAPERS_FILE", "failed_papers.md")

# PDFs the user downloaded for failed papers (decision 0020). The app keeps only their
# paths, in USER_PDF_INDEX; the files stay where they are.
PDF_WATCH_DIR = os.path.expanduser(os.getenv("PDF_WATCH_DIR", "~/Downloads"))
PDF_SCAN_DAYS = float(os.getenv("PDF_SCAN_DAYS", "7"))
USER_PDF_INDEX = os.getenv("USER_PDF_INDEX", os.path.join(REPORTS_DIR, "user_pdfs.json"))

# Web search during reviews (decision 0022). The key lives only in TAVILY_KEY_PATH, a
# private file outside the repo; never put it in .env, whose values reach child processes.
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
TAVILY_KEY_PATH = Path.home() / ".config" / "scholar-summary" / "tavily_key"
WEB_SEARCH_MAX_QUERIES = int(os.getenv("WEB_SEARCH_MAX_QUERIES", "3"))
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
WEB_SEARCH_SNIPPET_CHARS = int(os.getenv("WEB_SEARCH_SNIPPET_CHARS", "1000"))
WEB_SEARCH_MONTHLY_CREDIT_CAP = int(os.getenv("WEB_SEARCH_MONTHLY_CREDIT_CAP", "800"))
# Prompt tokens the review scheduler allows for results: 3 x 5 x 1,000 chars plus labels.
WEB_SEARCH_TOKEN_RESERVE = int(os.getenv("WEB_SEARCH_TOKEN_RESERVE", "5000"))
WEB_SEARCH_LOG_PATH = os.getenv("WEB_SEARCH_LOG_PATH", os.path.join(REPORTS_DIR, "web_search_log.jsonl"))

# OpenReview login (decision 0023). Like the Tavily key, it lives only in this private file,
# written by scripts/setup_openreview.py; never put it in .env.
OPENREVIEW_CREDENTIALS_PATH = Path.home() / ".config" / "scholar-summary" / "openreview.env"

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
