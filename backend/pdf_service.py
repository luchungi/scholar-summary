import io
import re
from pathlib import Path
from typing import Optional, Generator, Tuple
from urllib.parse import urlparse
import requests

import academic_api
import paper_retriever

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

def resolve_pdf_url(url: str, title: Optional[str] = None, timeout: int = 10) -> Optional[str]:
    """
    Resolves the direct PDF URL for a given paper URL or title.
    Returns the direct PDF URL or local file path, or None if no open-access PDF is available.
    """
    if not url:
        return None

    # Handle local uploaded files
    if url.startswith("file://"):
        local_path = url[7:]
        if Path(local_path).exists():
            return url
        # Check in temp uploads or reports dir
        candidate = Path("reports/temp_uploads") / Path(local_path).name
        if candidate.exists():
            return f"file://{candidate.resolve()}"
        return None

    # 1. arXiv: fast-path
    arxiv_id = academic_api.extract_arxiv_id(url)
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    # 2. Check Academic APIs (Semantic Scholar / Crossref)
    try:
        api_result = academic_api.get_paper_by_academic_api(url, title)
        if api_result and api_result.get("pdf_url"):
            candidate_pdf = api_result["pdf_url"]
            print(f"[PDF Service] Academic API resolved PDF URL: {candidate_pdf}")
            return candidate_pdf
    except Exception as e:
        print(f"[PDF Service] Academic API check failed: {e}")

    # 3. Check domain rules in url/rules.json
    try:
        resolved_url = paper_retriever.resolve_url(url, timeout=timeout)
        parsed = urlparse(resolved_url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        rules_schema = paper_retriever.load_rules()
        if domain in rules_schema:
            rules_list = rules_schema[domain].get("rules", [])
            candidate, is_none = paper_retriever.apply_rules(resolved_url, rules_list, timeout=timeout)
            if not is_none and candidate:
                return candidate
            elif is_none:
                # Marked as no PDF / HTML only
                return None
    except Exception as e:
        print(f"[PDF Service] Rule check failed: {e}")

    # 4. Check if direct URL or resolved URL yields PDF
    try:
        candidate_url = paper_retriever.resolve_url(url, timeout=timeout)
        resp = requests.head(candidate_url, headers=HEADERS, allow_redirects=True, timeout=timeout)
        content_type = resp.headers.get("Content-Type", "").lower()
        if "application/pdf" in content_type or candidate_url.lower().endswith(".pdf"):
            return candidate_url
    except Exception:
        pass

    # 5. Check if URL ends with .pdf
    if url.lower().endswith(".pdf"):
        return url

    return None

def stream_pdf(resolved_pdf_url: str, chunk_size: int = 65536) -> Generator[bytes, None, None]:
    """
    Generator that streams PDF bytes in chunks directly to the response.
    """
    if resolved_pdf_url.startswith("file://"):
        local_path = Path(resolved_pdf_url[7:])
        if not local_path.exists():
            raise FileNotFoundError(f"Local PDF file not found: {local_path}")
        with open(local_path, "rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk
        return

    # Remote streaming
    with requests.get(resolved_pdf_url, headers=HEADERS, stream=True, timeout=25) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "application/pdf" not in content_type and not resolved_pdf_url.lower().endswith(".pdf"):
            raise ValueError(f"Target URL did not return application/pdf (returned {content_type})")
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                yield chunk

def download_pdf_bytes(resolved_pdf_url: str, timeout: int = 25) -> Optional[bytes]:
    """
    Downloads and returns entire PDF bytes (used when creating a bundled zip archive).
    """
    try:
        if resolved_pdf_url.startswith("file://"):
            local_path = Path(resolved_pdf_url[7:])
            if local_path.exists():
                return local_path.read_bytes()
            return None

        resp = requests.get(resolved_pdf_url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "").lower()
            if "application/pdf" in content_type or resolved_pdf_url.lower().endswith(".pdf") or resp.content[:4] == b"%PDF":
                return resp.content
    except Exception as e:
        print(f"[PDF Service] Failed to download PDF bytes from {resolved_pdf_url}: {e}")
    return None
