import io
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from pypdf import PdfReader

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

def resolve_url(url, timeout=10):
    """
    Follows redirects to find the final landing page URL.
    """
    try:
        response = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=timeout)
        return response.url
    except Exception as e:
        # If HEAD request fails, try GET
        try:
            response = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=timeout, stream=True)
            return response.url
        except Exception:
            return url

def extract_text_from_pdf(pdf_bytes):
    """
    Extracts text from PDF bytes using pypdf.
    """
    pdf_file = io.BytesIO(pdf_bytes)
    reader = PdfReader(pdf_file)
    text_content = []
    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            text_content.append(text)
    return "\n\n".join(text_content)

def scrape_html_text(html_content):
    """
    Extracts clean text from HTML content, removing scripts, styles, headers, footers, etc.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Remove script, style, style-related tags, nav, footer, header
    for element in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe"]):
        element.decompose()
        
    # Get text
    raw_text = soup.get_text(separator="\n")
    
    # Clean up whitespace
    lines = (line.strip() for line in raw_text.splitlines())
    # Break multi-headlines into a line each
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    # Drop blank lines
    clean_text = "\n".join(chunk for chunk in chunks if chunk)
    return clean_text

def retrieve_paper_text(url, timeout=15):
    """
    Retrieves the full text of a paper from a URL.
    Supports:
    - arXiv links (automatically downloads PDF)
    - Direct PDF links
    - Standard HTML pages (scrapes clean text)
    """
    print(f"Resolving URL: {url}")
    resolved_url = resolve_url(url, timeout)
    print(f"Resolved to: {resolved_url}")
    
    # Check if this is an arXiv URL
    parsed = urlparse(resolved_url)
    if "arxiv.org" in parsed.netloc:
        # Convert abs or html links to PDF download URL
        # E.g. https://arxiv.org/abs/2304.00001 -> https://arxiv.org/pdf/2304.00001
        path = parsed.path
        if path.startswith("/abs/"):
            arxiv_id = path.replace("/abs/", "")
            resolved_url = f"https://arxiv.org/pdf/{arxiv_id}"
            print(f"Detected arXiv URL. Converted to PDF endpoint: {resolved_url}")
        elif path.startswith("/html/"):
            arxiv_id = path.replace("/html/", "")
            resolved_url = f"https://arxiv.org/pdf/{arxiv_id}"
            print(f"Detected arXiv URL. Converted to PDF endpoint: {resolved_url}")
            
    # Attempt to fetch content
    try:
        print(f"Fetching content from: {resolved_url} ...")
        # Stream the request first to inspect headers
        response = requests.get(resolved_url, headers=HEADERS, timeout=timeout, stream=True)
        response.raise_for_status()
        
        content_type = response.headers.get("Content-Type", "").lower()
        
        # If it's a PDF
        if "application/pdf" in content_type or resolved_url.lower().endswith(".pdf"):
            print("Downloading and parsing PDF...")
            pdf_bytes = response.content
            text = extract_text_from_pdf(pdf_bytes)
            if text.strip():
                return text
            else:
                print("Warning: Extracted PDF text is empty. Trying fallback scraper on landing page.")
                
        # If it's HTML or other text formats
        print("Parsing content as HTML...")
        # Read the full content for HTML
        response = requests.get(resolved_url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        text = scrape_html_text(response.text)
        return text
        
    except Exception as e:
        print(f"Error retrieving paper text from {resolved_url}: {e}")
        return None
