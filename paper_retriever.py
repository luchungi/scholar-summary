import io
import os
import re
import json
import threading
from pathlib import Path
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import pymupdf
import agent

import config
import openreview_client

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
    Extracts text from PDF bytes using PyMuPDF.
    sort=True orders blocks by position, which keeps two-column
    academic layouts in natural reading order.
    """
    text_content = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text = page.get_text("text", sort=True)
            if text and text.strip():
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

def is_pdf_bytes(data):
    """
    True if the bytes are a PDF. Sites serve PDFs from links with no .pdf ending and with
    a generic Content-Type (repository "/bitstreams/<id>/download" links), and serve HTML
    challenge pages from links that do end in .pdf, so the content decides, not the name.
    """
    return b"%PDF-" in (data or b"")[:1024]

# What a bot-protection page says instead of the paper (Cloudflare, Akamai, AWS WAF,
# Anubis, OpenReview, Springer). Such a page is short, so the phrases are only looked for
# in short texts: a real paper may well mention a CAPTCHA.
_CHALLENGE_PHRASES = re.compile(
    r"just a moment|enable javascript|javascript is disabled|enable js\b|captcha|"
    r"verify(?:ing)? (?:that )?you(?:'re| are)(?: not a robot| human)|verifying your browser|"
    r"client challenge|not a (?:bot|robot)|access denied|security check|unusual activity|"
    r"request (?:is|was) blocked|checking your browser",
    re.IGNORECASE,
)
CHALLENGE_MAX_CHARS = 2500
# HTTP statuses a site answers with when it turns a script away. (A 503 counts only when
# the page also reads like a browser check: a server that is simply down says 503 too.)
BLOCKED_STATUSES = {403, 405, 429}
# Below this a page has nothing to judge a paper by, not even an abstract.
MIN_READABLE_CHARS = 300
MIN_ABSTRACT_CHARS = 200

def looks_like_bot_challenge(text):
    return len(text) <= CHALLENGE_MAX_CHARS and bool(_CHALLENGE_PHRASES.search(text))

_ABSTRACT_META_NAMES = ("citation_abstract", "dc.description", "dcterms.abstract", "eprints.abstract",
                        "og:description", "twitter:description", "description")
_TITLE_META_NAMES = ("citation_title", "dc.title", "og:title")

def extract_page_metadata(html_content):
    """
    Reads the paper's title and abstract out of a landing page's metadata: the <meta> tags
    publishers write for Google Scholar, and the JSON that IEEE Xplore embeds in a script
    (its visible page text is menus only). Returns {"title": str|None, "abstract": str|None}.
    """
    title, abstract = None, None
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        found = {}
        for meta in soup.find_all("meta"):
            name = (meta.get("name") or meta.get("property") or "").strip().lower()
            content = " ".join((meta.get("content") or "").split())
            if name and content and len(content) > len(found.get(name, "")):
                found[name] = content
        title = next((found[n] for n in _TITLE_META_NAMES if found.get(n)), None)
        candidates = [BeautifulSoup(found[n], "html.parser").get_text(" ") for n in _ABSTRACT_META_NAMES if found.get(n)]
        if candidates:
            abstract = " ".join(max(candidates, key=len).split())
    except Exception as e:
        print(f"[-] Error reading page metadata: {e}")

    match = re.search(r"xplGlobal\.document\.metadata\s*=\s*(\{.*?\});\s*$", html_content, re.DOTALL | re.MULTILINE)
    if match:
        try:
            data = json.loads(match.group(1))
            ieee_abstract = " ".join(BeautifulSoup(data.get("abstract") or "", "html.parser").get_text(" ").split())
            if len(ieee_abstract) > len(abstract or ""):
                abstract = ieee_abstract
            title = data.get("title") or data.get("displayDocTitle") or title
        except Exception:
            pass
    return {"title": title or None, "abstract": abstract or None}

def _fetch(url, timeout=15):
    """
    GETs a URL once and says what came back.
    Returns {"url", "status", "body", "html", "is_pdf", "error"}; html is None for a PDF.
    """
    page = {"url": url, "status": None, "body": b"", "html": None, "is_pdf": False, "error": None}
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        page["status"] = response.status_code
        page["body"] = response.content or b""
        page["is_pdf"] = is_pdf_bytes(page["body"])
        if not page["is_pdf"]:
            page["html"] = response.text
    except Exception as e:
        page["error"] = str(e)
    return page

def _pdf_text(page):
    """Text of a fetched PDF, or "" if it has none (a scan) or cannot be opened."""
    try:
        return extract_text_from_pdf(page["body"])
    except Exception as e:
        print(f"[-] Could not parse the PDF from {page['url']}: {e}")
        return ""

def classify_page(page):
    """
    Decides what a fetched non-PDF page is worth. Returns a dict with "coverage":
      "full"     - enough text to review as the paper itself
      "abstract" - a landing page: an abstract or a short description, not the paper
      "blocked"  - the site turned the request away (bot protection)
      "failed"   - nothing usable
    plus "text", "abstract", "title" and, for blocked/failed, a "reason".
    """
    if page["error"]:
        return {"coverage": "failed", "text": "", "reason": f"Could not reach the site ({page['error'][:150]})"}

    html = page["html"] or ""
    try:
        text = scrape_html_text(html)
    except Exception:
        text = ""
    status = page["status"]

    if status in BLOCKED_STATUSES or looks_like_bot_challenge(text):
        detail = f"HTTP {status}" if status != 200 else "it answered with a browser-check page"
        return {"coverage": "blocked", "text": "", "reason": f"Blocked by the site's bot protection ({detail})"}
    if status is not None and status >= 400:
        return {"coverage": "failed", "text": "", "reason": f"The site returned HTTP {status}"}

    meta = extract_page_metadata(html)
    abstract = meta["abstract"] if meta["abstract"] and len(meta["abstract"]) >= MIN_ABSTRACT_CHARS else None
    if len(text) >= config.HTML_FULLTEXT_MIN_CHARS:
        return {"coverage": "full", "text": text, "abstract": abstract, "title": meta["title"]}
    if abstract or len(text) >= MIN_READABLE_CHARS:
        return {"coverage": "abstract", "text": text, "abstract": abstract, "title": meta["title"]}
    return {"coverage": "failed", "text": "", "title": meta["title"],
            "reason": f"The page had no readable paper text ({len(text)} characters)"}

URL_RULES_PATH = Path(config.URL_RULES_PATH)

def load_rules():
    if not URL_RULES_PATH.exists():
        return {}
    try:
        with open(URL_RULES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading rules from {URL_RULES_PATH}: {e}")
        return {}

# Triage fetches papers in parallel (0012.3), so rule writes re-read the file under a
# lock and replace it atomically: a stale copy can't drop another thread's new rule,
# and a reader never sees a half-written file.
_rules_lock = threading.Lock()

def save_rules(rules):
    try:
        URL_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = URL_RULES_PATH.with_name(URL_RULES_PATH.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2)
        os.replace(tmp_path, URL_RULES_PATH)
    except Exception as e:
        print(f"Error saving rules to {URL_RULES_PATH}: {e}")

def set_domain_rule(domain, rules_list):
    with _rules_lock:
        rules_schema = load_rules()
        rules_schema[domain] = {"rules": rules_list}
        save_rules(rules_schema)

def write_none_rule(domain):
    set_domain_rule(domain, [{"type": "none"}])

def apply_rules(url, rules_list, html_content=None, timeout=15):
    """
    Applies the ordered rules for URL conversion.
    Returns: (resolved_url, is_none)
    """
    for rule in rules_list:
        rule_type = rule.get("type")
        if rule_type == "none":
            return None, True

        elif rule_type == "direct":
            return url, False

        elif rule_type == "regex_replace":
            pattern = rule.get("pattern")
            replacement = rule.get("replacement")
            if pattern and replacement:
                try:
                    match = re.search(pattern, url)
                    if match:
                        groupdict = match.groupdict()
                        groups = match.groups()
                        resolved = replacement
                        try:
                            # Safely format with regex captured named/positional groups
                            fmt_args = {}
                            if groupdict:
                                fmt_args.update(groupdict)
                            for i, g in enumerate(groups):
                                fmt_args[str(i)] = g
                                fmt_args[str(i+1)] = g
                            resolved = resolved.format(**fmt_args)
                        except Exception:
                            # Fallback if manual format replacement fails
                            for k, v in groupdict.items():
                                resolved = resolved.replace(f"{{{k}}}", v)
                            for i, g in enumerate(groups):
                                resolved = resolved.replace(f"{{{i}}}", g)
                                resolved = resolved.replace(f"{{{i+1}}}", g)
                        return resolved, False
                except Exception as e:
                    print(f"Error applying regex_replace rule: {e}")

        elif rule_type == "css_selector":
            selector = rule.get("selector")
            attr = rule.get("attribute", "href")
            if selector:
                if not html_content:
                    try:
                        resp = requests.get(url, headers=HEADERS, timeout=timeout)
                        resp.raise_for_status()
                        html_content = resp.text
                    except Exception as e:
                        print(f"Error fetching page for css_selector: {e}")
                        continue
                try:
                    soup = BeautifulSoup(html_content, "html.parser")
                    element = soup.select_one(selector)
                    if element and element.has_attr(attr):
                        val = element[attr]
                        resolved = urljoin(url, val)
                        return resolved, False
                except Exception as e:
                    print(f"Error applying css_selector rule: {e}")

    return url, False

def learn_rules_for_domain(url, domain, html_content, attempt=1, error_context=None, timeout=15):
    """
    Uses the agent to propose a rule, tests it, and saves it if successful.
    """
    print(f"--- Learning PDF retrieval rules for domain: {domain} (Attempt {attempt}/2) ---")
    soup = BeautifulSoup(html_content, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text().strip()
        if href and (len(text) > 0 or "pdf" in href.lower() or "download" in href.lower()):
            links.append(f"Text: {text[:50]} | Link: {href}")

    pdf_links = [l for l in links if "pdf" in l.lower() or "download" in l.lower()]
    other_links = [l for l in links if l not in pdf_links]
    selected_links = (pdf_links + other_links)[:150]
    links_summary = "\n".join(selected_links)

    try:
        rule = agent.propose_pdf_rule(url, links_summary, error_context)
        print(f"Agent proposed rule: {json.dumps(rule)}")
    except Exception as e:
        # The LLM call failing says nothing about the site, so no rule is saved: the next
        # paper from this domain gets another try. This paper falls back to the page text.
        print(f"[-] Agent failed to propose a rule: {e}")
        return None

    rule_type = rule.get("type")
    if rule_type == "none":
        print(f"Agent determined domain {domain} has no PDF/is paywalled.")
        write_none_rule(domain)
        return None

    try:
        resolved_url, is_none = apply_rules(url, [rule], html_content, timeout)
        if is_none or not resolved_url:
            raise ValueError("Rule resolved to None or empty URL.")

        print(f"Testing proposed rule: {rule_type}. Resolved URL: {resolved_url}")

        # Test download
        response = requests.get(resolved_url, headers=HEADERS, timeout=timeout, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()

        if "application/pdf" in content_type or resolved_url.lower().endswith(".pdf"):
            print("[+] Test SUCCESS! Retrieved PDF content.")
            set_domain_rule(domain, [rule])
            return resolved_url
        else:
            raise ValueError(f"URL did not return PDF content (Content-Type: {content_type}).")
    except Exception as e:
        error_msg = str(e)
        print(f"[-] Test failed for proposed rule: {error_msg}")
        if attempt < 2:
            print("[*] Retrying rule discovery with failure details...")
            return learn_rules_for_domain(url, domain, html_content, attempt + 1, error_msg, timeout)
        else:
            print("[-] Both learning attempts failed. Falling back to HTML.")
            write_none_rule(domain)
            return None

REFERENCE_HEADINGS = re.compile(
    r'^\s*(?:\d+\.?\s*)?(references|bibliography|works cited)\s*:?\s*$',
    re.IGNORECASE | re.MULTILINE
)

def strip_references(text):
    """
    Cuts the text at the last references/bibliography heading, provided it appears
    in the latter part of the document (to avoid cutting at a table-of-contents entry).
    """
    matches = list(REFERENCE_HEADINGS.finditer(text))
    if not matches:
        return text
    cut_pos = matches[-1].start()
    if cut_pos > len(text) * 0.3:
        print(f"[+] Stripped references section ({len(text) - cut_pos} chars removed).")
        return text[:cut_pos]
    return text

def truncate_to_budget(text, max_chars=None):
    """
    Fits text into the configured character budget, keeping the start (abstract,
    intro, methods) and the end (conclusion) since those carry the most signal.
    Returns (text, was_truncated).
    """
    if max_chars is None:
        max_chars = config.MAX_PAPER_CHARS
    if len(text) <= max_chars:
        return text, False
    head_len = int(max_chars * 0.75)
    tail_len = max_chars - head_len
    truncated = (
        text[:head_len]
        + "\n\n[... middle of paper truncated to fit the model's context window ...]\n\n"
        + text[-tail_len:]
    )
    print(f"[+] Truncated paper text from {len(text)} to ~{max_chars} chars (kept start and end).")
    return truncated, True

def prepare_paper_text(text):
    """
    Applies reference stripping and budget truncation. Returns (text, was_truncated).
    """
    text = strip_references(text)
    return truncate_to_budget(text)

GENERIC_TITLES = ("Manual URL Analysis", "Manual Input Paper", "Untitled", "Untitled Resource")

def retrieve_paper(url, timeout=15, title=None):
    """
    Retrieves a paper's text and says how much of the paper it is.
    Always returns a dict:
      "coverage": "full"     - the paper itself (text is ready for review)
                  "abstract" - only a landing page / abstract was reachable
                  "blocked"  - the site's bot protection turned the request away
                  "failed"   - nothing usable came back
      "text":      prepared text for "full", the page text for "abstract", else None
      "source":    "pdf" | "html" | None
      "raw_chars", "truncated": as before, for "full"
      "abstract":  the abstract, when the page or an academic API gave one
      "title":     a clean title from the page or an API, when found
      "reason":    why there is no full text (for the Failed & Skipped tab)
      "note":      set when the text came from somewhere other than the link (arXiv copy)
      "user_pdf":  file name of the user's downloaded PDF, when the text came from it
    title: the paper's title if known; used to look for an arXiv copy when the link fails.
    """
    raw = _retrieve_raw(url, timeout, title)
    result = {
        "coverage": raw["coverage"],
        "text": None,
        "source": raw.get("source"),
        "raw_chars": len(raw.get("text") or ""),
        "truncated": False,
        "abstract": raw.get("abstract"),
        "title": raw.get("title"),
        "reason": raw.get("reason"),
        "note": raw.get("note"),
        "user_pdf": raw.get("user_pdf"),
    }
    if raw["coverage"] == "full":
        result["text"], result["truncated"] = prepare_paper_text(raw["text"])
    elif raw["coverage"] == "abstract":
        result["text"] = raw.get("text") or None
    return result

def retrieve_paper_text(url, timeout=15):
    """
    Backwards-compatible wrapper returning prepared full text only (None otherwise).
    """
    result = retrieve_paper(url, timeout)
    return result["text"] if result["coverage"] == "full" else None

def _usable_title(*candidates):
    for candidate in candidates:
        candidate = " ".join((candidate or "").split())  # also turns non-breaking spaces into spaces
        if candidate and candidate not in GENERIC_TITLES:
            return candidate
    return None

def _retrieve_raw(url, timeout=15, title=None):
    """
    Retrieves the full text of a paper from a URL.
    Order:
    - A PDF the user downloaded for this paper
    - The OpenReview API for openreview.net links, when a login is set up (0023). This
      replaces the two steps below, because OpenReview's site challenges scripts
    - Academic API retrieval (arXiv, Semantic Scholar)
    - Domain specific URL rules (loaded dynamically from url/rules.json), learned for a
      new domain by the LLM agent
    - The page itself: a PDF if that is what comes back, else its HTML, classified by
      classify_page
    - If that did not give the paper: an arXiv copy with the same title
    Returns a dict with "coverage" (see retrieve_paper) and "text"/"source"/"reason"/...
    """
    import academic_api
    import paper_store

    # A PDF the user downloaded for this paper comes first (decision 0020).
    user_pdf = paper_store.pdf_for(url)
    if user_pdf:
        print(f"[+] Using the PDF the user downloaded: {user_pdf}")
        try:
            text = extract_text_from_pdf(Path(user_pdf).read_bytes())
        except Exception as e:
            print(f"[-] Could not read {user_pdf}: {e}")
            text = ""
        if text.strip():
            return {"coverage": "full", "text": text, "source": "pdf", "user_pdf": Path(user_pdf).name}
        print("[-] The user's PDF has no extractable text. Trying the link.")

    print(f"Resolving URL: {url}")
    api_title, api_abstract = None, None

    outcome = _retrieve_from_openreview(url)
    if outcome and outcome["coverage"] == "full":
        return outcome

    if outcome is None:
        # Try academic API resolution first
        try:
            api_result = academic_api.get_paper_by_academic_api(url)
            if api_result:
                api_title = api_result.get("title") or None
                api_abstract = api_result.get("abstract") or None
            if api_result and api_result.get("pdf_url"):
                pdf_url = api_result["pdf_url"]
                print(f"[+] Resolved direct PDF URL via Academic API: {pdf_url}")
                print(f"Fetching content from: {pdf_url} ...")
                page = _fetch(pdf_url, timeout)
                if page["is_pdf"]:
                    print("Downloading and parsing PDF...")
                    text = _pdf_text(page)
                    if text.strip():
                        return {"coverage": "full", "text": text, "source": "pdf", "title": api_title}
                    print("Warning: Extracted PDF text from Academic API was empty. Falling back to web scraper.")
                else:
                    print(f"[-] Academic API link did not return a PDF (HTTP {page['status']}). Falling back to web scraper.")
        except Exception as api_err:
            print(f"[-] Academic API resolution error/fallback: {api_err}")

        outcome = _retrieve_from_site(url, timeout)
        if outcome["coverage"] == "full":
            outcome["title"] = _usable_title(api_title, outcome.get("title"))
            return outcome

    # The link did not give the paper. Look for an arXiv copy under the same title.
    search_title = _usable_title(api_title, outcome.get("title"), title)
    if search_title:
        try:
            match = academic_api.find_arxiv_by_title(search_title)
            if match:
                page = _fetch(match["pdf_url"], max(timeout, 30))
                text = _pdf_text(page) if page["is_pdf"] else ""
                if text.strip():
                    return {
                        "coverage": "full", "text": text, "source": "pdf", "title": match["title"],
                        "note": (f"arXiv copy {match['arxiv_id']} found by title, because the linked page "
                                 f"did not give the paper ({outcome.get('reason') or 'abstract only'})"),
                    }
        except Exception as e:
            print(f"[-] arXiv title lookup failed: {e}")

    if not outcome.get("abstract") and api_abstract and len(api_abstract) >= MIN_ABSTRACT_CHARS:
        outcome["abstract"] = api_abstract
    outcome["title"] = _usable_title(api_title, outcome.get("title"))
    return outcome

def _retrieve_from_openreview(url):
    """
    Fetches an openreview.net paper through its API (decision 0023). Returns None when this
    does not apply, else a dict with "coverage" and what goes with it (see classify_page).
    """
    paper = openreview_client.fetch_paper(url)
    if paper is None:
        return None
    print(f"Fetching from the OpenReview API: {url}")
    reason = paper["reason"]
    if paper["pdf"] is not None:
        if is_pdf_bytes(paper["pdf"]):
            text = _pdf_text({"url": url, "body": paper["pdf"]})
            if text.strip():
                print("[+] Got the PDF from the OpenReview API.")
                return {"coverage": "full", "text": text, "source": "pdf", "title": _usable_title(paper["title"])}
            reason = "The PDF has no extractable text (probably scanned images)"
        else:
            reason = "OpenReview did not return a PDF"
    print(f"[-] {reason}: {url}")
    abstract = paper["abstract"]
    return {
        "coverage": "blocked" if paper["blocked"] else "failed",
        "text": "",
        "source": None,
        "title": _usable_title(paper["title"]),
        "abstract": abstract if abstract and len(abstract) >= MIN_ABSTRACT_CHARS else None,
        "reason": reason,
    }

def _retrieve_from_site(url, timeout=15):
    """
    Fetches the paper from its own site, through the domain's URL rule if there is one.
    Returns a dict with "coverage" and what goes with it (see classify_page).
    """
    resolved_url = resolve_url(url, timeout)
    print(f"Resolved to: {resolved_url}")

    parsed = urlparse(resolved_url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    rules_schema = load_rules()
    fetch_url = resolved_url
    fetched = None  # the page at resolved_url, when it has already been downloaded

    if domain in rules_schema:
        print(f"Found existing rule for domain: {domain}")
        rules_list = rules_schema[domain].get("rules", [])
        rule_url, is_none = apply_rules(resolved_url, rules_list, timeout=timeout)
        if is_none:
            # No PDF rule for this domain. The page itself is still read: it may hold an
            # abstract, and some links on such a domain are PDFs in their own right.
            print(f"Domain {domain} has no PDF rule. Reading the page itself.")
        elif rule_url:
            fetch_url = rule_url
    else:
        print(f"No rule for {domain} yet. Fetching: {resolved_url}")
        fetched = _fetch(resolved_url, timeout)
        if fetched["is_pdf"]:
            print(f"[+] Direct PDF detected. Saving 'direct' rule for domain: {domain}")
            set_domain_rule(domain, [{"type": "direct"}])
        elif fetched["error"] is None and classify_page(fetched)["coverage"] in ("full", "abstract"):
            print(f"Not a PDF. Learning rules for {domain}...")
            try:
                learned_url = learn_rules_for_domain(resolved_url, domain, fetched["html"], timeout=timeout)
                if learned_url:
                    fetch_url = learned_url
            except Exception as e:
                print(f"[-] Error learning rules: {e}")
        else:
            # A blocked or broken page says nothing about where the site keeps its PDFs,
            # so no rule is learned from it.
            print(f"[-] Could not read the page (HTTP {fetched['status']}); no rule learned for {domain}.")

    if fetch_url != resolved_url or fetched is None:
        print(f"Fetching content from: {fetch_url} ...")
        page = _fetch(fetch_url, timeout)
    else:
        page = fetched

    if page["is_pdf"]:
        print("Downloading and parsing PDF...")
        text = _pdf_text(page)
        if text.strip():
            return {"coverage": "full", "text": text, "source": "pdf"}
        print("Warning: Extracted PDF text is empty.")
        if fetch_url == resolved_url:
            return {"coverage": "failed", "text": "",
                    "reason": "The PDF has no extractable text (probably scanned images)"}

    if fetch_url != resolved_url:
        # The rule's link gave no PDF text. Fall back to the landing page.
        print("Resolved URL did not give a PDF. Falling back to the landing page.")
        page = fetched or _fetch(resolved_url, timeout)
        if page["is_pdf"]:
            text = _pdf_text(page)
            if text.strip():
                return {"coverage": "full", "text": text, "source": "pdf"}
            return {"coverage": "failed", "text": "",
                    "reason": "The PDF has no extractable text (probably scanned images)"}

    print("Parsing content as HTML...")
    outcome = classify_page(page)
    outcome["source"] = "html" if outcome["coverage"] in ("full", "abstract") else None
    if outcome.get("reason"):
        print(f"[-] {outcome['reason']}: {page['url']}")
    return outcome
