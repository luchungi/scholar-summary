"""
Tests for how a paper's text is fetched from its link (paper_retriever).

They cover the failures found among the papers the app could not retrieve:
- a domain marked "none" (no PDF rule) lost its URL, so its page was never read;
- a PDF was recognised by its Content-Type or ".pdf" ending instead of its content;
- a bot-protection page was taken for the paper and reviewed;
- an LLM error while learning a rule marked the whole domain as having no PDF;
- a paper blocked at the publisher was not looked for on arXiv.

All tests are offline: requests.get / requests.head are replaced by a stub.
"""

import json
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import academic_api
import config
import paper_retriever as pr


def make_pdf(text="A paper about rough path signatures. " * 40):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 550, 800), text, fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


def html_page(body="", head=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


CHALLENGE = html_page("<h1>Just a moment...</h1><p>Enable JavaScript and cookies to continue</p>")
ABSTRACT = "We study optimal execution with signature features and prove a convergence rate. " * 5
LANDING = html_page("<p>Journal menu</p>", f'<meta name="citation_title" content="A Clean Title of the Paper">'
                                           f'<meta name="citation_abstract" content="{ABSTRACT}">')
FULL_TEXT = html_page("<p>" + "The full text of an open access article. " * 400 + "</p>")


class FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None, url=""):
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.url = url

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.content)

    def close(self):
        pass


@pytest.fixture
def web(monkeypatch, tmp_path):
    """
    Stubs the network and the rules file. `routes` maps a URL substring to a FakeResponse
    (or an exception); the longest matching substring wins. Unknown URLs answer 404.
    The academic APIs find nothing unless a test says otherwise.
    """
    class Web:
        def __init__(self):
            self.routes = {}
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append(url)
            for fragment in sorted(self.routes, key=len, reverse=True):
                if fragment in url:
                    result = self.routes[fragment]
                    if isinstance(result, Exception):
                        raise result
                    return result
            return FakeResponse(404)

        def head(self, url, **kwargs):
            return FakeResponse(200, url=url)

    stub = Web()
    monkeypatch.setattr(pr.requests, "get", stub.get)
    monkeypatch.setattr(pr.requests, "head", stub.head)
    monkeypatch.setattr(academic_api, "get_paper_by_academic_api", lambda url, title=None: None)
    monkeypatch.setattr(academic_api, "find_arxiv_by_title", lambda title: None)
    monkeypatch.setattr(pr, "URL_RULES_PATH", tmp_path / "rules.json")
    monkeypatch.setattr(config, "HTML_FULLTEXT_MIN_CHARS", 12000)
    return stub


def rules():
    return pr.load_rules()


def no_llm(*args, **kwargs):
    raise AssertionError("the LLM rule learner must not be called here")


# --- a domain marked "none" -----------------------------------------------------------

def test_none_rule_domain_still_reads_the_page(web):
    """The bug: apply_rules returned None for the URL, and the fallback then fetched 'None'."""
    pr.write_none_rule("paywalled.org")
    web.routes["paywalled.org/abstract/1"] = FakeResponse(200, LANDING)

    result = pr.retrieve_paper("https://paywalled.org/abstract/1")

    assert "None" not in web.calls
    assert result["coverage"] == "abstract"
    assert result["abstract"] == ABSTRACT.strip()
    assert result["title"] == "A Clean Title of the Paper"
    assert result["source"] == "html"


def test_none_rule_domain_link_that_is_a_pdf_is_read_as_a_pdf(web):
    """svedbergopen.com: marked "none" from a landing page, but its /download/ links are PDFs."""
    pr.write_none_rule("journal.org")
    web.routes["journal.org/article/download/637/499"] = FakeResponse(200, make_pdf())

    result = pr.retrieve_paper("https://journal.org/article/download/637/499")

    assert result["coverage"] == "full" and result["source"] == "pdf"
    assert "rough path signatures" in result["text"]


# --- recognising a PDF by its content ---------------------------------------------------

def test_pdf_without_pdf_ending_or_content_type_is_parsed_as_a_pdf(web, monkeypatch):
    """ruor.uottawa.ca /bitstreams/<id>/download: octet-stream, no .pdf; was scraped as HTML."""
    monkeypatch.setattr(pr, "learn_rules_for_domain", no_llm)
    web.routes["repo.edu/bitstreams/abc/download"] = FakeResponse(
        200, make_pdf(), headers={"Content-Type": "application/octet-stream"})

    result = pr.retrieve_paper("https://repo.edu/bitstreams/abc/download")

    assert result["coverage"] == "full" and result["source"] == "pdf"
    assert rules()["repo.edu"] == {"rules": [{"type": "direct"}]}


def test_html_served_from_a_pdf_link_is_not_parsed_as_a_pdf(web):
    """shs-conferences.org: a .pdf link that answers with a 'please enable JS' page."""
    pr.set_domain_rule("conf.org", [{"type": "direct"}])
    web.routes["conf.org/paper.pdf"] = FakeResponse(
        403, html_page("conf.org Please enable JS and disable any ad blocker"),
        headers={"Content-Type": "application/pdf"})

    result = pr.retrieve_paper("https://conf.org/paper.pdf")

    assert result["coverage"] == "blocked" and result["text"] is None


def test_scanned_pdf_with_no_text_fails_with_a_reason(web):
    pr.set_domain_rule("scans.org", [{"type": "direct"}])
    web.routes["scans.org/old.pdf"] = FakeResponse(200, make_pdf(text=""))

    result = pr.retrieve_paper("https://scans.org/old.pdf")

    assert result["coverage"] == "failed"
    assert "no extractable text" in result["reason"]


# --- bot-protection pages ---------------------------------------------------------------

@pytest.mark.parametrize("status, body", [
    (403, CHALLENGE),                                                     # Cloudflare
    (200, html_page("Client Challenge JavaScript is disabled in your browser.")),   # Springer
    (200, html_page("Verifying your browser | OpenReview Complete the check below")),
    (405, html_page("Human Verification ... solving a CAPTCHA puzzle")),            # NASA ADS
    (429, html_page("Service unavailable The request is blocked.")),                # IGI Global
    (200, html_page("Making sure you're not a bot! Anubis could not load its JavaScript.")),
    (403, html_page("Access Denied You don't have permission to access this server")),  # Akamai
])
def test_challenge_page_is_reported_as_blocked_not_as_paper_text(web, status, body):
    pr.write_none_rule("guarded.org")
    web.routes["guarded.org/paper/1"] = FakeResponse(status, body)

    result = pr.retrieve_paper("https://guarded.org/paper/1")

    assert result["coverage"] == "blocked"
    assert result["text"] is None
    assert result["reason"].startswith("Blocked by the site's bot protection")


def test_blocked_page_teaches_no_rule(web, monkeypatch):
    """A challenge page on a new domain must not be shown to the rule learner, which would
    answer 'no PDF here' and mark the domain 'none' for good (aaltodoc.aalto.fi)."""
    monkeypatch.setattr(pr, "learn_rules_for_domain", no_llm)
    web.routes["newsite.org/item/1"] = FakeResponse(200, CHALLENGE)

    result = pr.retrieve_paper("https://newsite.org/item/1")

    assert result["coverage"] == "blocked"
    assert "newsite.org" not in rules()


def test_a_long_paper_that_mentions_captcha_is_not_a_challenge():
    text = "We train agents to solve CAPTCHA puzzles. " * 200
    assert not pr.looks_like_bot_challenge(text)
    assert pr.looks_like_bot_challenge("Just a moment... Enable JavaScript and cookies to continue")


def test_nearly_empty_page_fails_instead_of_being_reviewed(web):
    """repository.gatech.edu gave 21 characters, and a report was written from them."""
    pr.write_none_rule("empty.org")
    web.routes["empty.org/x"] = FakeResponse(200, html_page("Loading, please wait"))

    result = pr.retrieve_paper("https://empty.org/x")

    assert result["coverage"] == "failed"
    assert "no readable paper text" in result["reason"]


def test_site_error_and_unreachable_site_fail_with_a_reason(web):
    pr.write_none_rule("down.org")
    web.routes["down.org/a"] = FakeResponse(500, html_page("Internal Server Error"))
    web.routes["down.org/b"] = ConnectionError("timed out")

    assert pr.retrieve_paper("https://down.org/a")["reason"] == "The site returned HTTP 500"
    result = pr.retrieve_paper("https://down.org/b")
    assert result["coverage"] == "failed" and "Could not reach the site" in result["reason"]


# --- full text vs abstract --------------------------------------------------------------

def test_long_html_page_counts_as_the_paper(web):
    pr.write_none_rule("openjournal.org")
    web.routes["openjournal.org/article/9"] = FakeResponse(200, FULL_TEXT)

    result = pr.retrieve_paper("https://openjournal.org/article/9")

    assert result["coverage"] == "full" and result["source"] == "html"
    assert result["raw_chars"] > 12000


def test_ieee_abstract_is_read_from_the_embedded_json(web):
    """IEEE Xplore's visible text is menus only; title and abstract are in a script."""
    meta = {"title": "Position Sizing as a Risk-Control Variable", "abstract": ABSTRACT, "doi": "10.1109/x"}
    page = html_page("<p>IEEE Account Purchase Details</p>",
                     f"<script>xplGlobal.document.metadata={json.dumps(meta)};\n</script>")
    pr.write_none_rule("ieeexplore.ieee.org")
    web.routes["ieeexplore.ieee.org/abstract/document/11676654"] = FakeResponse(200, page)

    result = pr.retrieve_paper("https://ieeexplore.ieee.org/abstract/document/11676654/")

    assert result["coverage"] == "abstract"
    assert result["abstract"] == ABSTRACT.strip()
    assert result["title"] == "Position Sizing as a Risk-Control Variable"


def test_blocked_page_keeps_the_abstract_an_academic_api_gave(web, monkeypatch):
    """ACM / Emerald: the page is blocked, but Crossref has the abstract for the DOI."""
    monkeypatch.setattr(academic_api, "get_paper_by_academic_api", lambda url, title=None: {
        "title": "Paper Known to Crossref", "abstract": ABSTRACT, "pdf_url": None, "source": "crossref_doi"})
    web.routes["dl.acm.org/doi/abs/10.1145/1.2"] = FakeResponse(403, CHALLENGE)

    result = pr.retrieve_paper("https://dl.acm.org/doi/abs/10.1145/1.2")

    assert result["coverage"] == "blocked"
    assert result["abstract"] == ABSTRACT
    assert result["title"] == "Paper Known to Crossref"


# --- rule learning ----------------------------------------------------------------------

def test_llm_error_while_learning_does_not_mark_the_domain_none(web, monkeypatch):
    def broken(*args, **kwargs):
        raise TimeoutError("LLM server not running")
    monkeypatch.setattr(pr.agent, "propose_pdf_rule", broken)
    web.routes["fresh.org/article/3"] = FakeResponse(200, LANDING)

    result = pr.retrieve_paper("https://fresh.org/article/3")

    assert result["coverage"] == "abstract"       # this paper falls back to the page
    assert "fresh.org" not in rules()             # the next one gets another try


def test_learned_rule_is_followed_to_the_pdf(web, monkeypatch):
    monkeypatch.setattr(pr.agent, "propose_pdf_rule", lambda url, links, err=None: {
        "type": "regex_replace", "pattern": r"^(?P<base>https://ojs\.org/article)/view/(?P<id>\d+)",
        "replacement": "{base}/download/{id}"})
    web.routes["ojs.org/article/view/7"] = FakeResponse(200, LANDING)
    web.routes["ojs.org/article/download/7"] = FakeResponse(200, make_pdf(), headers={"Content-Type": "application/pdf"})

    result = pr.retrieve_paper("https://ojs.org/article/view/7")

    assert result["coverage"] == "full" and result["source"] == "pdf"
    assert rules()["ojs.org"]["rules"][0]["type"] == "regex_replace"


def test_rule_link_that_gives_no_pdf_falls_back_to_the_landing_page(web):
    """link.springer.com: the rule's /content/pdf/ link answers with a challenge page."""
    pr.set_domain_rule("pub.org", [{"type": "regex_replace", "pattern": r"^https://pub\.org/article/(?P<id>.+)",
                                    "replacement": "https://pub.org/content/pdf/{id}.pdf"}])
    web.routes["pub.org/content/pdf/42.pdf"] = FakeResponse(200, CHALLENGE)
    web.routes["pub.org/article/42"] = FakeResponse(200, LANDING)

    result = pr.retrieve_paper("https://pub.org/article/42")

    assert result["coverage"] == "abstract" and result["abstract"] == ABSTRACT.strip()


# --- arXiv copy by title ----------------------------------------------------------------

def test_blocked_paper_is_read_from_its_arxiv_copy(web, monkeypatch):
    searched = []

    def find(title):
        searched.append(title)
        return {"arxiv_id": "2607.25996v1", "title": "RepoReasoner", "pdf_url": "https://arxiv.org/pdf/2607.25996v1"}
    monkeypatch.setattr(academic_api, "find_arxiv_by_title", find)
    web.routes["dl.acm.org/doi/pdf/10.1145/3808131"] = FakeResponse(403, CHALLENGE)
    web.routes["arxiv.org/pdf/2607.25996v1"] = FakeResponse(200, make_pdf())

    result = pr.retrieve_paper("https://dl.acm.org/doi/pdf/10.1145/3808131", title="RepoReasoner: Evaluating Code Reasoning")

    assert searched == ["RepoReasoner: Evaluating Code Reasoning"]
    assert result["coverage"] == "full" and result["source"] == "pdf"
    assert "arXiv copy 2607.25996v1 found by title" in result["note"]
    assert "Blocked by the site's bot protection" in result["note"]


def test_arxiv_is_not_searched_when_the_link_gave_the_paper_or_the_title_is_generic(web, monkeypatch):
    def find(title):
        raise AssertionError(f"searched arXiv for {title!r}")
    monkeypatch.setattr(academic_api, "find_arxiv_by_title", find)
    pr.set_domain_rule("ok.org", [{"type": "direct"}])
    web.routes["ok.org/p.pdf"] = FakeResponse(200, make_pdf())
    web.routes["dl.acm.org"] = FakeResponse(403, CHALLENGE)

    assert pr.retrieve_paper("https://ok.org/p.pdf", title="Some Real Paper Title")["coverage"] == "full"
    assert pr.retrieve_paper("https://dl.acm.org/doi/1", title="Manual URL Analysis")["coverage"] == "blocked"
    assert pr.retrieve_paper("https://dl.acm.org/doi/1")["coverage"] == "blocked"


def test_clean_page_title_is_preferred_for_the_arxiv_search(web, monkeypatch):
    """Old alert titles have words run together; the landing page's own title is clean."""
    searched = []
    monkeypatch.setattr(academic_api, "find_arxiv_by_title", lambda t: searched.append(t))
    pr.write_none_rule("paywalled.org")
    web.routes["paywalled.org/abstract/1"] = FakeResponse(200, LANDING)

    pr.retrieve_paper("https://paywalled.org/abstract/1", title="A CleanTitleof the Paper")

    assert searched == ["A Clean Title of the Paper"]


# --- the old wrapper --------------------------------------------------------------------

def test_retrieve_paper_text_returns_full_text_only(web):
    pr.write_none_rule("paywalled.org")
    pr.set_domain_rule("ok.org", [{"type": "direct"}])
    web.routes["paywalled.org/abstract/1"] = FakeResponse(200, LANDING)
    web.routes["ok.org/p.pdf"] = FakeResponse(200, make_pdf())

    assert pr.retrieve_paper_text("https://paywalled.org/abstract/1") is None
    assert "rough path signatures" in pr.retrieve_paper_text("https://ok.org/p.pdf")
