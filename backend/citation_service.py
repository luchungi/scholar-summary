import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from bs4 import BeautifulSoup

import academic_api

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

def format_author_name(name: str) -> str:
    """
    Normalizes an author name into 'Lastname, Firstname' format for EndNote.
    Examples:
      'Magnus Wiese' -> 'Wiese, Magnus'
      'Wiese, Magnus' -> 'Wiese, Magnus'
      'Blanka Horvath' -> 'Horvath, Blanka'
      'K. Jarrod Millman' -> 'Millman, K. Jarrod'
      'Stéfan J. van der Walt' -> 'van der Walt, Stéfan J.'
    """
    name = name.strip()
    if not name:
        return ""
    if "," in name:
        return name
        
    parts = name.split()
    if len(parts) == 1:
        return parts[0]
        
    # Check for suffix like Jr, III, etc.
    if parts[-1].lower() in ("jr", "jr.", "ii", "iii", "iv", "sr", "sr.") and len(parts) > 2:
        return f"{parts[-2]} {parts[-1]}, {' '.join(parts[:-2])}"
        
    # Check for surname particles like 'van', 'von', 'de', 'der', 'van der', 'da'
    particles = {"van", "von", "de", "der", "da", "di", "del", "della", "du", "la", "le"}
    if len(parts) >= 3 and parts[-2].lower() in particles:
        if len(parts) >= 4 and parts[-3].lower() in particles:
            # e.g., 'van der Walt'
            surname = " ".join(parts[-3:])
            given = " ".join(parts[:-3])
            return f"{surname}, {given}"
        surname = " ".join(parts[-2:])
        given = " ".join(parts[:-2])
        return f"{surname}, {given}"

    return f"{parts[-1]}, {' '.join(parts[:-1])}"

def clean_title_for_filename(title: str, max_words: int = 6) -> str:
    """
    Sanitizes title into a short, safe string for filenames.
    """
    # Remove leading '# ' or other markdown
    clean = re.sub(r'^[#\s]+', '', title).strip()
    # Replace non-alphanumeric with spaces
    words = re.findall(r'[a-zA-Z0-9]+', clean)
    if not words:
        return "Paper"
    selected = words[:max_words]
    return "_".join(selected)

def get_academic_filename_base(metadata: Dict[str, Any]) -> str:
    """
    Generates academic standard filename base: {Author}_{Year}_{ShortTitle}
    Example: 'Wiese_2026_GROMM_Generative_Risk_neutral_Option_Market'
    """
    authors = metadata.get("authors", [])
    if authors:
        first_author = authors[0]
        # Extract surname (before comma or last word)
        if "," in first_author:
            surname = first_author.split(",")[0].strip()
        else:
            surname = first_author.split()[-1]
        author_part = re.sub(r'[^a-zA-Z0-9]', '', surname) or "Author"
    else:
        author_part = "Paper"

    year = str(metadata.get("year") or "").strip()
    if not re.match(r'^\d{4}$', year):
        # Look for 4 digits in year string
        m = re.search(r'\b(19\d\d|20\d\d)\b', year)
        year_part = m.group(1) if m else "UnknownYear"
    else:
        year_part = year

    title_part = clean_title_for_filename(metadata.get("title", "Paper"))
    return f"{author_part}_{year_part}_{title_part}"

def extract_metadata_from_report(report_path: str) -> Dict[str, Any]:
    """
    Fallback parser that extracts metadata from the locally generated markdown report.
    """
    data: Dict[str, Any] = {}
    path = Path(report_path)
    if not path.exists():
        return data

    try:
        content = path.read_text(encoding="utf-8")
        
        # 1. Title
        title_m = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if title_m:
            data["title"] = title_m.group(1).strip()
            
        # 2. URL
        url_m = re.search(r'\*\*Link\*\*:\s*\[?([^\s\]\)]+)', content)
        if url_m:
            data["url"] = url_m.group(1).strip()

        # 3. Authors
        authors_m = re.search(r'\*\*\s*Authors?\s*\*\*\s*:\s*([^\n]+)', content, re.IGNORECASE)
        if authors_m:
            raw_authors = authors_m.group(1).strip()
            # Clean possible markdown bold/italics
            raw_authors = raw_authors.replace("*", "").replace("`", "")
            # Split authors by ';' or ',' or ' and '
            parts = re.split(r'[,;]|\band\b', raw_authors)
            author_list = []
            for p in parts:
                cleaned = p.strip()
                if cleaned and cleaned.lower() not in ("unknown", "n/a", "none", "et al.", "et al"):
                    author_list.append(format_author_name(cleaned))
            if author_list:
                data["authors"] = author_list

        # 4. Venue/Journal
        venue_m = re.search(r'\*\*\s*Venue(?:/Journal)?\s*\*\*\s*:\s*([^\n]+)', content, re.IGNORECASE)
        if venue_m:
            venue = venue_m.group(1).strip().replace("*", "").replace("`", "")
            if venue and "unknown" not in venue.lower():
                data["journal"] = venue

        # 5. Year
        year_m = re.search(r'\*\*\s*Year\s*\*\*\s*:\s*([^\n]+)', content, re.IGNORECASE)
        if year_m:
            ym = re.search(r'\b(19\d\d|20\d\d)\b', year_m.group(1))
            if ym:
                data["year"] = ym.group(1)

        # 6. Abstract / Summary snippet
        ideas_m = re.search(r'###\s*4\.\s*Key High-Level Ideas[\s\S]*?(?=###|\Z)', content, re.IGNORECASE)
        if ideas_m:
            # Strip markdown formatting
            text = ideas_m.group(0).strip()
            text = re.sub(r'#+\s*', '', text)
            text = " ".join(text.split()[:150]) # First 150 words
            data["abstract"] = text

    except Exception as e:
        print(f"[-] Error extracting metadata from report {report_path}: {e}")

    return data

def query_crossref_full(doi: str) -> Optional[Dict[str, Any]]:
    """
    Fetches comprehensive bibliographic metadata for a DOI from Crossref.
    """
    clean_doi = academic_api.extract_doi_from_url(doi) or doi
    url = f"https://api.crossref.org/works/{clean_doi}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            work = resp.json().get("message", {})
            title_list = work.get("title", [])
            title = title_list[0] if title_list else None
            
            authors = []
            for a in work.get("author", []):
                family = a.get("family", "").strip()
                given = a.get("given", "").strip()
                if family and given:
                    authors.append(f"{family}, {given}")
                elif family:
                    authors.append(family)
                elif a.get("name"):
                    authors.append(format_author_name(a.get("name")))

            container = work.get("container-title", [])
            journal = container[0] if container else None
            
            # Published year
            pub_parts = (
                work.get("published", {}).get("date-parts")
                or work.get("published-print", {}).get("date-parts")
                or work.get("published-online", {}).get("date-parts")
                or [[]]
            )
            year = str(pub_parts[0][0]) if pub_parts[0] else None

            # Abstract
            abstract = work.get("abstract") or ""
            abstract = re.sub(r'<[^>]+>', '', abstract).strip()

            return {
                "title": title,
                "authors": authors,
                "journal": journal,
                "year": year,
                "volume": work.get("volume"),
                "issue": work.get("issue"),
                "pages": work.get("page"),
                "doi": clean_doi,
                "url": work.get("resource", {}).get("primary", {}).get("URL") or f"https://doi.org/{clean_doi}",
                "abstract": abstract,
                "ref_type": "Journal Article" if work.get("type") == "journal-article" else "Conference Proceedings",
                "source": "crossref"
            }
    except Exception as e:
        print(f"[-] Crossref query error: {e}")
    return None

def query_arxiv_full(arxiv_id: str) -> Optional[Dict[str, Any]]:
    """
    Queries arXiv Atom API and extracts full metadata including all authors and published year.
    """
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
            entry = root.find("atom:entry", ns)
            if entry is not None:
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                published_el = entry.find("atom:published", ns)
                journal_ref_el = entry.find("arxiv:journal_ref", ns)
                doi_el = entry.find("arxiv:doi", ns)

                title = " ".join(title_el.text.split()) if title_el is not None else None
                abstract = " ".join(summary_el.text.split()) if summary_el is not None else ""

                authors = []
                for a in entry.findall("atom:author", ns):
                    name_el = a.find("atom:name", ns)
                    if name_el is not None and name_el.text:
                        authors.append(format_author_name(name_el.text))

                year = None
                if published_el is not None and published_el.text:
                    ym = re.search(r'\b(19\d\d|20\d\d)\b', published_el.text)
                    if ym:
                        year = ym.group(1)

                journal = journal_ref_el.text.strip() if journal_ref_el is not None and journal_ref_el.text else "arXiv preprint"
                doi = doi_el.text.strip() if doi_el is not None and doi_el.text else None

                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                for link in entry.findall("atom:link", ns):
                    if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                        pdf_url = link.attrib.get("href")
                        break
                if pdf_url.startswith("http://"):
                    pdf_url = "https://" + pdf_url[7:]

                return {
                    "title": title,
                    "authors": authors,
                    "journal": journal,
                    "year": year,
                    "doi": doi,
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "pdf_url": pdf_url,
                    "abstract": abstract,
                    "ref_type": "Preprint",
                    "source": "arxiv"
                }
    except Exception as e:
        print(f"[-] arXiv query error: {e}")
    return None

def query_html_citation_tags(url: str, timeout: int = 8) -> Dict[str, Any]:
    """
    Scrapes Google Scholar citation meta tags from the webpage HTML.
    e.g. <meta name="citation_title" content="...">
         <meta name="citation_author" content="...">
         <meta name="citation_publication_date" content="...">
    """
    meta: Dict[str, Any] = {}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Title
            title_tag = soup.find("meta", attrs={"name": re.compile(r"^(?:citation_|dc\.)title$", re.I)})
            if title_tag and title_tag.get("content"):
                meta["title"] = title_tag["content"].strip()
                
            # Authors
            author_tags = soup.find_all("meta", attrs={"name": re.compile(r"^(?:citation_|dc\.)(?:author|creator)$", re.I)})
            authors = [format_author_name(t["content"]) for t in author_tags if t.get("content")]
            if authors:
                meta["authors"] = authors

            # Date / Year
            date_tag = soup.find("meta", attrs={"name": re.compile(r"^(?:citation_|dc\.)(?:publication_date|date)$", re.I)})
            if date_tag and date_tag.get("content"):
                ym = re.search(r'\b(19\d\d|20\d\d)\b', date_tag["content"])
                if ym:
                    meta["year"] = ym.group(1)

            # Journal
            journal_tag = soup.find("meta", attrs={"name": re.compile(r"^citation_journal_title$", re.I)})
            if journal_tag and journal_tag.get("content"):
                meta["journal"] = journal_tag["content"].strip()

            # DOI
            doi_tag = soup.find("meta", attrs={"name": re.compile(r"^(?:citation_|dc\.)doi$", re.I)})
            if doi_tag and doi_tag.get("content"):
                meta["doi"] = doi_tag["content"].strip()

            # PDF URL
            pdf_tag = soup.find("meta", attrs={"name": re.compile(r"^citation_pdf_url$", re.I)})
            if pdf_tag and pdf_tag.get("content"):
                meta["pdf_url"] = pdf_tag["content"].strip()
    except Exception as e:
        print(f"[-] HTML meta tags scrape error: {e}")
    return meta

def resolve_paper_metadata(url: str, title: str, report_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Main metadata resolution engine with multi-source waterfall:
    1. arXiv API (if arXiv URL/ID)
    2. Crossref API (if DOI in URL or page)
    3. Local report parsing fallback
    4. HTML citation meta tags
    5. Clean defaults
    """
    metadata: Dict[str, Any] = {
        "title": title,
        "url": url,
        "authors": [],
        "journal": None,
        "year": None,
        "volume": None,
        "issue": None,
        "pages": None,
        "doi": None,
        "abstract": None,
        "ref_type": "Journal Article"
    }

    # 1. Check arXiv
    arxiv_id = academic_api.extract_arxiv_id(url)
    if arxiv_id:
        arxiv_data = query_arxiv_full(arxiv_id)
        if arxiv_data:
            metadata.update({k: v for k, v in arxiv_data.items() if v is not None})
            # If arXiv provided full authors and title, return immediately
            if metadata.get("authors") and metadata.get("year"):
                return metadata

    # 2. Check DOI via Crossref
    doi = academic_api.extract_doi_from_url(url)
    if doi:
        crossref_data = query_crossref_full(doi)
        if crossref_data:
            metadata.update({k: v for k, v in crossref_data.items() if v is not None})
            if metadata.get("authors") and metadata.get("year"):
                return metadata

    # 3. Fallback: Parse local report file if exists
    if report_path:
        report_meta = extract_metadata_from_report(report_path)
        for k, v in report_meta.items():
            if not metadata.get(k) and v:
                metadata[k] = v

    # 4. Fallback: HTML meta tags if authors or journal still missing
    if (not metadata.get("authors") or not metadata.get("journal")) and url.startswith("http"):
        html_meta = query_html_citation_tags(url)
        for k, v in html_meta.items():
            if not metadata.get(k) and v:
                metadata[k] = v

    # Final sanity checks
    if not metadata.get("title") or metadata.get("title") in ("Manual URL Analysis", "Untitled"):
        metadata["title"] = title

    if not metadata.get("authors"):
        metadata["authors"] = ["Unknown Author"]

    return metadata

def generate_enw_content(metadata: Dict[str, Any], pdf_local_path: Optional[str] = None) -> str:
    """
    Serializes metadata dictionary into standard EndNote Refer (.enw) format.
    If pdf_local_path is provided (or present in metadata["pdf_local_path"]),
    includes the %< and %> tags so EndNote automatically attaches the PDF.
    """
    lines = []
    
    # %0 Reference Type
    ref_type = metadata.get("ref_type") or "Journal Article"
    lines.append(f"%0 {ref_type}")

    # %T Title
    if metadata.get("title"):
        lines.append(f"%T {metadata['title']}")

    # %A Authors (one line per author)
    for author in metadata.get("authors", []):
        if author.strip():
            lines.append(f"%A {author.strip()}")

    # %J / %B Journal / Conference
    if metadata.get("journal"):
        lines.append(f"%J {metadata['journal']}")
        lines.append(f"%B {metadata['journal']}")

    # %D Publication Year
    if metadata.get("year"):
        lines.append(f"%D {metadata['year']}")

    # %V Volume
    if metadata.get("volume"):
        lines.append(f"%V {metadata['volume']}")

    # %N Issue / Number
    if metadata.get("issue"):
        lines.append(f"%N {metadata['issue']}")

    # %P Pages
    if metadata.get("pages"):
        lines.append(f"%P {metadata['pages']}")

    # %R DOI
    if metadata.get("doi"):
        lines.append(f"%R {metadata['doi']}")

    # %U URL
    if metadata.get("url"):
        lines.append(f"%U {metadata['url']}")

    # %< File Attachment (PDF) and %> Link to PDF
    target_pdf = pdf_local_path or metadata.get("pdf_local_path")
    if target_pdf:
        lines.append(f"%< {target_pdf}")
        lines.append(f"%> {target_pdf}")

    # %X Abstract
    if metadata.get("abstract"):
        clean_abstract = " ".join(metadata['abstract'].split())
        lines.append(f"%X {clean_abstract}")

    return "\n".join(lines) + "\n\n"

def generate_combined_enw(metadata_list: List[Dict[str, Any]]) -> str:
    """
    Generates a combined .enw file with multiple references for bulk import.
    """
    return "".join(generate_enw_content(m, m.get("pdf_local_path")) for m in metadata_list)
