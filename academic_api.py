import re
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from typing import Dict, Any, Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

def extract_arxiv_id(text: str) -> Optional[str]:
    """
    Extracts arXiv ID from a URL or text string.
    Matches:
    - arxiv.org/abs/2304.12345
    - arxiv.org/pdf/2304.12345.pdf
    - 2304.12345
    """
    match = re.search(r'(?:arxiv\.org/(?:abs|pdf)/|arxiv:)?([a-z\-]+(?:\.[a-z\-]+)*/\d{7}|\d{4}\.\d{4,5}(?:v\d+)?)', text, re.IGNORECASE)
    if match:
        return match.group(1)
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
    1. If arXiv url, use arXiv API
    2. If DOI exists in URL, try Semantic Scholar DOI query. Fallback to Crossref.
    3. If title is provided, try Semantic Scholar Search
    """
    # 1. Check arXiv
    arxiv_id = extract_arxiv_id(url)
    if arxiv_id:
        res = fetch_arxiv_by_id(arxiv_id)
        if res:
            return res
            
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
