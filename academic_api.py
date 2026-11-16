import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
import requests
from typing import Dict, Any, List, Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

# NASA ADS serves its abstract pages behind a CAPTCHA, but an ADS identifier (bibcode) for
# an arXiv record carries the arXiv ID: 2026arXiv261041855S -> 2610.41855, and the
# pre-2015 four-digit form 2014arXiv1412.6980K -> 1412.6980.
_ADS_ARXIV_BIBCODE = re.compile(r'(?<!\d)\d{4}arXiv(\d{4})(?:\.(\d{4})|(\d{5}))(?=[A-Za-z.]|$)')
_ADS_URL_BIBCODE = re.compile(r'adsabs\.harvard\.edu/(?:abs|link_gateway)/([^/?#]+)', re.IGNORECASE)
ADS_GATEWAY_URL = "https://ui.adsabs.harvard.edu/link_gateway/{bibcode}/EPRINT_PDF"

def extract_arxiv_id(text: str) -> Optional[str]:
    """
    Extracts arXiv ID from a URL or text string.
    Matches:
    - arxiv.org/abs/2304.12345
    - arxiv.org/pdf/2304.12345.pdf
    - 2304.12345
    - ui.adsabs.harvard.edu/abs/2026arXiv261041855S/abstract (ADS record of an arXiv paper)
    """
    ads = _ADS_ARXIV_BIBCODE.search(urllib.parse.unquote(text))
    if ads:
        return f"{ads.group(1)}.{ads.group(2) or ads.group(3)}"
    match = re.search(r'(?:arxiv\.org/(?:abs|pdf)/|arxiv:)?([a-z\-]+(?:\.[a-z\-]+)*/\d{7}|\d{4}\.\d{4,5}(?:v\d+)?)', text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def extract_ads_bibcode(url: str) -> Optional[str]:
    """
    Extracts the ADS identifier from a NASA ADS URL, e.g.
    ui.adsabs.harvard.edu/abs/2016PhRvL.116f1102A/abstract -> 2016PhRvL.116f1102A
    """
    match = _ADS_URL_BIBCODE.search(url or "")
    return urllib.parse.unquote(match.group(1)) if match else None

def resolve_ads_eprint_arxiv_id(url: str, timeout: int = 10) -> Optional[str]:
    """
    For an ADS record whose identifier is not an arXiv one (a journal paper), asks ADS's
    link gateway where the e-print lives. The gateway answers with a plain redirect and
    is not behind the CAPTCHA that blocks the abstract page. Returns the arXiv ID the
    redirect points to, or None if the record has no arXiv e-print.
    """
    bibcode = extract_ads_bibcode(url)
    if not bibcode:
        return None
    gateway = ADS_GATEWAY_URL.format(bibcode=urllib.parse.quote(bibcode, safe=""))
    try:
        print(f"[Academic API] Asking the ADS link gateway for the e-print of {bibcode}")
        response = requests.get(gateway, headers=HEADERS, timeout=timeout, allow_redirects=False, stream=True)
        response.close()
        target = response.headers.get("Location", "") if response.status_code in (301, 302, 303, 307, 308) else ""
        host = urllib.parse.urlparse(target).netloc.lower()
        if host == "arxiv.org" or host.endswith(".arxiv.org"):
            return extract_arxiv_id(target)
        print(f"[Academic API] ADS has no arXiv e-print for {bibcode} (HTTP {response.status_code}).")
    except Exception as e:
        print(f"[-] Error querying the ADS link gateway: {e}")
    return None

def extract_doi_from_url(url: str) -> Optional[str]:
    """
    Extracts DOI from URL.
    """
    match = re.search(r'(10\.\d{4,9}/[a-zA-Z0-9._;()/:#-]+)', url)
    if match:
        doi = match.group(1)
        if doi.endswith('.'):
            doi = doi[:-1]
        return doi
    return None

def fetch_arxiv_by_id(arxiv_id: str) -> Optional[Dict[str, Any]]:
    """
    Queries the arXiv API for a specific arXiv ID.
    """
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    try:
        print(f"[Academic API] Querying arXiv API for ID: {arxiv_id}")
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None
        
        # Parse XML
        root = ET.fromstring(response.content)
        # Namespace for Atom syndication format
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return None
            
        title_el = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)
        
        if title_el is None:
            return None
            
        title = " ".join(title_el.text.split())
        abstract = " ".join(summary_el.text.split()) if summary_el is not None else ""
        
        # Look for PDF link
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href")
                break
                
        # Clean up pdf url (ensure it is https)
        if pdf_url.startswith("http://"):
            pdf_url = "https://" + pdf_url[7:]
            
        return {
            "title": title,
            "abstract": abstract,
            "pdf_url": pdf_url,
            "source": "arxiv"
        }
    except Exception as e:
        print(f"[-] Error querying arXiv API: {e}")
    return None

# --- arXiv copy of a paper whose publisher page cannot be read (looked up by title) ---

# arXiv asks for at most one API request every three seconds; triage fetches papers in
# parallel, so title searches queue up behind this lock.
ARXIV_SEARCH_MIN_INTERVAL = 3.0
_arxiv_search_lock = threading.Lock()
_arxiv_last_search = 0.0

# How alike two titles must be, compared as lowercase letters and digits only, to count as
# the same paper. Titles under 30 such characters must match exactly: a short title like
# "Portfolio Optimization" is too easy to share between different papers.
TITLE_MATCH_THRESHOLD = 0.92
TITLE_MATCH_MIN_CHARS = 15
TITLE_EXACT_BELOW_CHARS = 30

_TITLE_STOPWORDS = {"with", "from", "using", "based", "towards", "toward", "through", "under", "into", "approach"}

def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())

def title_similarity(a: str, b: str) -> float:
    a, b = normalize_title(a), normalize_title(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def titles_match(a: str, b: str) -> bool:
    shortest = min(len(normalize_title(a)), len(normalize_title(b)))
    if shortest < TITLE_MATCH_MIN_CHARS:
        return False
    similarity = title_similarity(a, b)
    return similarity == 1.0 if shortest < TITLE_EXACT_BELOW_CHARS else similarity >= TITLE_MATCH_THRESHOLD

def _title_search_words(title: str) -> List[str]:
    """
    The words worth searching for: the six longest. A word with a capital after a lowercase
    letter ("DeepReinforcement") is two words that an old alert title ran together, and
    would match nothing, so it is left out.
    """
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", title or "")
    words = [w.strip("-") for w in words if not re.search(r"[a-z][A-Z]", w)]
    seen, unique = set(), []
    for w in words:
        if len(w) >= 4 and w.lower() not in seen and w.lower() not in _TITLE_STOPWORDS:
            seen.add(w.lower())
            unique.append(w)
    return sorted(unique, key=len, reverse=True)[:6]

def _arxiv_title_query(query: str) -> Optional[List[Dict[str, str]]]:
    """One throttled arXiv search. Returns [{"arxiv_id", "title"}], or None if arXiv did not answer."""
    global _arxiv_last_search
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode({"search_query": query, "max_results": 10})
    with _arxiv_search_lock:
        wait = ARXIV_SEARCH_MIN_INTERVAL - (time.monotonic() - _arxiv_last_search)
        if wait > 0:
            time.sleep(wait)
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
        except Exception as e:
            print(f"[-] Error searching arXiv by title: {e}")
            return None
        finally:
            _arxiv_last_search = time.monotonic()
    if response.status_code != 200:
        print(f"[Academic API] arXiv title search returned HTTP {response.status_code}.")
        return None
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return None
    entries = []
    for entry in root.findall("atom:entry", ns):
        id_el, title_el = entry.find("atom:id", ns), entry.find("atom:title", ns)
        if id_el is None or title_el is None or not id_el.text or not title_el.text:
            continue
        entries.append({"arxiv_id": id_el.text.rsplit("/abs/", 1)[-1], "title": " ".join(title_el.text.split())})
    return entries

def find_arxiv_by_title(title: str) -> Optional[Dict[str, Any]]:
    """
    Looks for an arXiv copy of a paper by its title. Used when the publisher's page is
    blocked or paywalled. Searches for papers whose title holds all the main words, then,
    if that finds nothing (an old alert title with words run together), any of them; a hit
    counts only if titles_match says it is the same title.
    Returns {"arxiv_id", "title", "pdf_url", "source": "arxiv_title"} or None.
    """
    words = _title_search_words(title)
    if len(words) < 2 or len(normalize_title(title)) < TITLE_MATCH_MIN_CHARS:
        return None
    print(f"[Academic API] Searching arXiv for a copy titled: {title}")
    for joiner in (" AND ", " OR "):
        entries = _arxiv_title_query(joiner.join(f'ti:"{w}"' for w in words))
        if entries is None:
            return None
        for entry in sorted(entries, key=lambda e: -title_similarity(e["title"], title)):
            if titles_match(entry["title"], title):
                print(f"[Academic API] Found arXiv copy {entry['arxiv_id']}: {entry['title']}")
                return {
                    "arxiv_id": entry["arxiv_id"],
                    "title": entry["title"],
                    "pdf_url": f"https://arxiv.org/pdf/{entry['arxiv_id']}",
                    "source": "arxiv_title",
                }
    print("[Academic API] No arXiv copy with a matching title.")
    return None

def fetch_semantic_scholar_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    """
    Queries Semantic Scholar API for a specific DOI.
    """
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,abstract,openAccessPdf,externalIds"
    try:
        print(f"[Academic API] Querying Semantic Scholar for DOI: {doi}")
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            title = data.get("title")
            abstract = data.get("abstract") or ""
            open_access_pdf = data.get("openAccessPdf")
            pdf_url = open_access_pdf.get("url") if open_access_pdf else None
            
            if title:
                return {
                    "title": title,
                    "abstract": abstract,
                    "pdf_url": pdf_url,
                    "source": "semantic_scholar_doi",
                    "doi": doi
                }
        elif response.status_code == 429:
            print("[Academic API] [WARNING] Semantic Scholar rate limit hit (429) during DOI fetch.")
        else:
            print(f"[Academic API] Semantic Scholar returned status code {response.status_code} for DOI.")
    except Exception as e:
        print(f"[-] Error querying Semantic Scholar DOI: {e}")
    return None

def fetch_semantic_scholar_by_title(title: str) -> Optional[Dict[str, Any]]:
    """
    Queries Semantic Scholar search API for a paper by title.
    """
    safe_title = urllib.parse.quote(title)
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={safe_title}&limit=1&fields=title,abstract,openAccessPdf,externalIds"
    try:
        print(f"[Academic API] Searching Semantic Scholar for title: {title}")
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            papers = data.get("data", [])
            if papers:
                paper = papers[0]
                title = paper.get("title")
                abstract = paper.get("abstract") or ""
                open_access_pdf = paper.get("openAccessPdf")
                pdf_url = open_access_pdf.get("url") if open_access_pdf else None
                external_ids = paper.get("externalIds", {})
                doi = external_ids.get("DOI")
                
                return {
                    "title": title,
                    "abstract": abstract,
                    "pdf_url": pdf_url,
                    "source": "semantic_scholar_search",
                    "doi": doi
                }
        elif response.status_code == 429:
            print("[Academic API] [WARNING] Semantic Scholar rate limit hit (429) during title search.")
        else:
            print(f"[Academic API] Semantic Scholar returned status code {response.status_code} for title search.")
    except Exception as e:
        print(f"[-] Error querying Semantic Scholar search: {e}")
    return None

def fetch_crossref_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    """
    Queries Crossref API to resolve DOI metadata.
    """
    url = f"https://api.crossref.org/works/{doi}"
    try:
        print(f"[Academic API] Querying Crossref for DOI: {doi}")
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            work = data.get("message", {})
            title_list = work.get("title", [])
            title = title_list[0] if title_list else None
            
            # Crossref abstract is often wrapped in XML tags, clean if exists
            abstract = work.get("abstract") or ""
            abstract = re.sub(r'<[^>]+>', '', abstract).strip()
            
            resource = work.get("resource", {})
            primary_url = resource.get("primary", {}).get("URL")
            
            if title:
                return {
                    "title": title,
                    "abstract": abstract,
                    "pdf_url": None,  # Crossref does not guarantee direct PDF url
                    "primary_url": primary_url,
                    "source": "crossref_doi",
                    "doi": doi
                }
    except Exception as e:
        print(f"[-] Error querying Crossref API: {e}")
    return None

def get_paper_by_academic_api(url: str, title: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Tries to retrieve paper metadata and direct PDF URL using academic APIs.
    Priority:
    1. If arXiv url, or a NASA ADS url that leads to an arXiv paper, use arXiv API
    2. If DOI exists in URL, try Semantic Scholar DOI query. Fallback to Crossref.
    3. If title is provided, try Semantic Scholar Search
    """
    # 1. Check arXiv (directly, or through a NASA ADS link to an arXiv paper)
    is_ads = extract_ads_bibcode(url) is not None
    arxiv_id = extract_arxiv_id(url)
    if not arxiv_id and is_ads:
        arxiv_id = resolve_ads_eprint_arxiv_id(url)
    if arxiv_id:
        res = fetch_arxiv_by_id(arxiv_id)
        if res:
            return res
        if is_ads:
            # The ADS page itself is behind a CAPTCHA, so there is nothing to fall back
            # to: hand over the arXiv PDF even when the arXiv API did not answer.
            return {"title": "", "abstract": "", "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}", "source": "arxiv"}

    # 2. Check DOI
    doi = extract_doi_from_url(url)
    if doi:
        # Try Semantic Scholar first for direct PDF link
        res = fetch_semantic_scholar_by_doi(doi)
        if res and res.get("pdf_url"):
            return res
            
        # Fallback to Crossref to get clean metadata (title, primary URL)
        res_cross = fetch_crossref_by_doi(doi)
        if res_cross:
            return res_cross
            
    # 3. Check Title search on Semantic Scholar
    if title and title not in ("Manual URL Analysis", "Manual Input Paper", "Untitled"):
        res = fetch_semantic_scholar_by_title(title)
        if res and res.get("pdf_url"):
            t1 = title.lower().strip()
            t2 = res.get("title", "").lower().strip()
            # Simple soft title matching
            if re.sub(r'\W+', '', t1) == re.sub(r'\W+', '', t2) or t1[:30] in t2 or t2[:30] in t1:
                return res
                
    return None
