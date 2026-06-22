import io
import re
import json
from pathlib import Path
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from pypdf import PdfReader
import agent

import config

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

def save_rules(rules):
    try:
        URL_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(URL_RULES_PATH, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2)
    except Exception as e:
        print(f"Error saving rules to {URL_RULES_PATH}: {e}")

def write_none_rule(domain):
    rules_schema = load_rules()
    rules_schema[domain] = {"rules": [{"type": "none"}]}
    save_rules(rules_schema)

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
        print(f"[-] Agent failed to propose a rule: {e}")
        write_none_rule(domain)
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
            rules_schema = load_rules()
            rules_schema[domain] = {"rules": [rule]}
            save_rules(rules_schema)
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

def retrieve_paper_text(url, timeout=15):
    """
    Retrieves the full text of a paper from a URL.
    Supports:
    - Domain specific URL rules (loaded dynamically from url/rules.json)
    - Automatically discovers rules for new domains using LLM agent
    - Fallback to HTML scraping
    """
    print(f"Resolving URL: {url}")
    resolved_url = resolve_url(url, timeout)
    print(f"Resolved to: {resolved_url}")

    parsed = urlparse(resolved_url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    rules_schema = load_rules()
    use_html_fallback = False

    if domain in rules_schema:
        print(f"Found existing rule for domain: {domain}")
        rules_list = rules_schema[domain].get("rules", [])
        resolved_url, is_none = apply_rules(resolved_url, rules_list, timeout=timeout)
        if is_none:
            print(f"Domain {domain} is marked as HTML fallback only.")
            use_html_fallback = True
    else:
        # Check if original URL directly points to PDF
        try:
            print(f"Checking if URL directly yields PDF: {resolved_url}")
            resp = requests.head(resolved_url, headers=HEADERS, allow_redirects=True, timeout=timeout)
            content_type = resp.headers.get("Content-Type", "").lower()
            if "application/pdf" in content_type or resolved_url.lower().endswith(".pdf"):
                print(f"[+] Direct PDF detected. Saving 'direct' rule for domain: {domain}")
                rules_schema[domain] = {"rules": [{"type": "direct"}]}
                save_rules(rules_schema)
            else:
                print(f"Direct check did not yield PDF. Fetching HTML to learn rules for {domain}...")
                get_resp = requests.get(resolved_url, headers=HEADERS, timeout=timeout)
                get_resp.raise_for_status()
                html_content = get_resp.text

                learned_url = learn_rules_for_domain(resolved_url, domain, html_content, timeout=timeout)
                if learned_url:
                    resolved_url = learned_url
                else:
                    use_html_fallback = True
        except Exception as e:
            print(f"[-] Error checking or learning rules: {e}")
            use_html_fallback = True

    try:
        if not use_html_fallback:
            print(f"Fetching content from: {resolved_url} ...")
            response = requests.get(resolved_url, headers=HEADERS, timeout=timeout, stream=True)
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "").lower()
            if "application/pdf" in content_type or resolved_url.lower().endswith(".pdf"):
                print("Downloading and parsing PDF...")
                pdf_bytes = response.content
                text = extract_text_from_pdf(pdf_bytes)
                if text.strip():
                    return text
                else:
                    print("Warning: Extracted PDF text is empty. Trying fallback scraper on landing page.")
            else:
                print("Resolved URL was not a PDF. Falling back to HTML scraping.")

        print("Parsing content as HTML...")
        response = requests.get(resolved_url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        text = scrape_html_text(response.text)
        return text

    except Exception as e:
        print(f"Error retrieving paper text from {resolved_url}: {e}")
        return None

