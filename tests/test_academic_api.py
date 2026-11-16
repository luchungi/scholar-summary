"""
Tests for routing NASA ADS links to arXiv.

ui.adsabs.harvard.edu serves its abstract pages behind a CAPTCHA, so an ADS link is
resolved without loading that page: the arXiv ID is read out of the ADS identifier, or,
for a journal record, taken from the redirect of ADS's link gateway.

All tests here are offline: requests.get is replaced by a stub that records every URL.
"""

import sys
from pathlib import Path
from urllib.parse import unquote_plus as urllib_unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import academic_api

ARXIV_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2610.41855v1</id>
    <title>Iterated Integrals as Lexical
      Fingerprints</title>
    <summary>An abstract.</summary>
    <link title="pdf" href="http://arxiv.org/pdf/2610.41855v1" type="application/pdf"/>
  </entry>
</feed>"""


class FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def close(self):
        pass


@pytest.fixture
def web(monkeypatch):
    """Stub requests.get. `routes` maps a URL substring to a FakeResponse or an exception."""
    class Web:
        def __init__(self):
            self.routes = {}
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append(url)
            for fragment, result in self.routes.items():
                if fragment in url:
                    if isinstance(result, Exception):
                        raise result
                    return result
            return FakeResponse(404)

    stub = Web()
    monkeypatch.setattr(academic_api.requests, "get", stub.get)
    return stub


# --- reading the arXiv ID out of an ADS identifier ---

@pytest.mark.parametrize("url, expected", [
    ("https://ui.adsabs.harvard.edu/abs/2026arXiv261041855S/abstract", "2610.41855"),
    ("https://ui.adsabs.harvard.edu/abs/2026arXiv260711720K", "2607.11720"),
    ("https://ui.adsabs.harvard.edu/abs/2014arXiv1412.6980K/abstract", "1412.6980"),
    ("https://ui.adsabs.harvard.edu/abs/2014arXiv1412%2E6980K/abstract", "1412.6980"),
    ("2026arXiv260520348S", "2605.20348"),
])
def test_arxiv_id_is_decoded_from_an_ads_identifier(url, expected):
    assert academic_api.extract_arxiv_id(url) == expected


@pytest.mark.parametrize("url", [
    "https://ui.adsabs.harvard.edu/abs/2016PhRvL.116f1102A/abstract",     # journal record
    "https://ui.adsabs.harvard.edu/abs/2020A%26A...641A...6P/abstract",
    "https://example.org/some/paper",
])
def test_no_arxiv_id_in_a_journal_ads_identifier(url):
    assert academic_api.extract_arxiv_id(url) is None


@pytest.mark.parametrize("url, expected", [
    ("https://arxiv.org/abs/2304.12345", "2304.12345"),
    ("https://arxiv.org/pdf/2304.12345v2.pdf", "2304.12345v2"),
    ("https://arxiv.org/abs/hep-th/9901001", "hep-th/9901001"),
    ("arXiv:1706.03762", "1706.03762"),
])
def test_plain_arxiv_links_still_resolve_as_before(url, expected):
    assert academic_api.extract_arxiv_id(url) == expected


@pytest.mark.parametrize("url, expected", [
    ("https://ui.adsabs.harvard.edu/abs/2016PhRvL.116f1102A/abstract", "2016PhRvL.116f1102A"),
    ("https://ui.adsabs.harvard.edu/abs/2020A%26A...641A...6P/abstract", "2020A&A...641A...6P"),
    ("https://ui.adsabs.harvard.edu/link_gateway/2026arXiv261041855S/EPRINT_PDF", "2026arXiv261041855S"),
    ("https://arxiv.org/abs/2304.12345", None),
    ("", None),
])
def test_ads_identifier_is_read_from_the_url(url, expected):
    assert academic_api.extract_ads_bibcode(url) == expected


# --- resolving a paper ---

def test_ads_arxiv_link_goes_straight_to_arxiv_without_touching_ads(web):
    web.routes["export.arxiv.org"] = FakeResponse(200, ARXIV_ATOM)
    result = academic_api.get_paper_by_academic_api(
        "https://ui.adsabs.harvard.edu/abs/2026arXiv261041855S/abstract")
    assert result["pdf_url"] == "https://arxiv.org/pdf/2610.41855v1"
    assert result["title"] == "Iterated Integrals as Lexical Fingerprints"
    assert len(web.calls) == 1 and "id_list=2610.41855" in web.calls[0]
    assert not any("adsabs" in url for url in web.calls)


def test_journal_ads_link_is_resolved_through_the_gateway_redirect(web):
    web.routes["link_gateway/2016PhRvL.116f1102A/EPRINT_PDF"] = FakeResponse(
        302, headers={"Location": "https://arxiv.org/pdf/1602.03837"})
    web.routes["export.arxiv.org"] = FakeResponse(200, ARXIV_ATOM)
    result = academic_api.get_paper_by_academic_api(
        "https://ui.adsabs.harvard.edu/abs/2016PhRvL.116f1102A/abstract")
    assert result["source"] == "arxiv"
    assert any("id_list=1602.03837" in url for url in web.calls)
    # The CAPTCHA-protected abstract page is never requested.
    assert not any("/abs/" in url for url in web.calls)


def test_gateway_identifier_is_url_encoded(web):
    academic_api.resolve_ads_eprint_arxiv_id("https://ui.adsabs.harvard.edu/abs/2020A%26A...641A...6P/abstract")
    assert web.calls == ["https://ui.adsabs.harvard.edu/link_gateway/2020A%26A...641A...6P/EPRINT_PDF"]


def test_ads_record_without_an_eprint_resolves_to_nothing(web):
    # The stub answers 404 for everything, as the gateway does for a record with no e-print.
    assert academic_api.get_paper_by_academic_api(
        "https://ui.adsabs.harvard.edu/abs/2016PhRvL.116f1102A/abstract") is None


def test_gateway_redirect_to_another_site_is_ignored(web):
    web.routes["link_gateway"] = FakeResponse(
        302, headers={"Location": "https://example.org/files/2016.12345.pdf"})
    assert academic_api.resolve_ads_eprint_arxiv_id(
        "https://ui.adsabs.harvard.edu/abs/2016PhRvL.116f1102A/abstract") is None


def test_gateway_error_is_swallowed(web):
    web.routes["link_gateway"] = ConnectionError("blocked")
    assert academic_api.resolve_ads_eprint_arxiv_id(
        "https://ui.adsabs.harvard.edu/abs/2016PhRvL.116f1102A/abstract") is None


def test_non_ads_url_never_calls_the_gateway(web):
    assert academic_api.resolve_ads_eprint_arxiv_id("https://example.org/paper") is None
    assert web.calls == []


def test_ads_link_still_yields_the_arxiv_pdf_when_the_arxiv_api_is_down(web):
    web.routes["export.arxiv.org"] = FakeResponse(503)
    result = academic_api.get_paper_by_academic_api(
        "https://ui.adsabs.harvard.edu/abs/2026arXiv261041855S/abstract")
    assert result["pdf_url"] == "https://arxiv.org/pdf/2610.41855"


def test_plain_arxiv_link_keeps_its_old_fallthrough_when_the_arxiv_api_is_down(web):
    web.routes["export.arxiv.org"] = FakeResponse(503)
    assert academic_api.get_paper_by_academic_api("https://arxiv.org/abs/2610.41855") is None


# --- finding an arXiv copy by title ---

def atom(*entries):
    body = "".join(f"<entry><id>http://arxiv.org/abs/{i}</id><title>{t}</title></entry>" for i, t in entries)
    return FakeResponse(200, f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'.encode())


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(academic_api, "ARXIV_SEARCH_MIN_INTERVAL", 0.0)


REPO_TITLE = "RepoReasoner: Evaluating Repository-Level Code Reasoning Ability of Long-Context Language Models"


def test_arxiv_copy_is_found_by_title(web, no_wait):
    web.routes["export.arxiv.org"] = atom(
        ("2601.00001v1", "Evaluating Repository-Level Code Completion of Language Models"),
        ("2607.25996v1", "RepoReasoner: Evaluating Repository-Level Code Reasoning\n  Ability of Long-Context Language Models"))

    match = academic_api.find_arxiv_by_title(REPO_TITLE)

    assert match["arxiv_id"] == "2607.25996v1"
    assert match["pdf_url"] == "https://arxiv.org/pdf/2607.25996v1"
    assert len(web.calls) == 1 and "+AND+" in web.calls[0]


def test_title_with_words_run_together_still_matches(web, no_wait):
    """Titles saved before the alert parser was fixed: the glued words are left out of the
    search, and the comparison ignores spaces."""
    web.routes["export.arxiv.org"] = atom(("2607.11720v1", "Active Offline-to-Online Reinforcement Learning"))

    match = academic_api.find_arxiv_by_title("Active Offline-to-OnlineReinforcement Learning")

    assert match["arxiv_id"] == "2607.11720v1"
    query = urllib_unquote(web.calls[0])
    assert "OnlineReinforcement" not in query and 'ti:"Learning"' in query


def test_search_widens_to_any_word_when_all_words_find_nothing(web, no_wait, monkeypatch):
    """'Learningfor' cannot be told apart from a real word, so the all-words search finds
    nothing; the any-word search does."""
    title = "DeepReinforcement Learningfor Adaptive Decision-Making in Markets"

    def get(url, **kwargs):
        web.calls.append(url)
        if "+AND+" in url:
            return atom()
        return atom(("2609.00002v2", "Deep Reinforcement Learning for Adaptive Decision-Making in Markets"))
    monkeypatch.setattr(academic_api.requests, "get", get)

    match = academic_api.find_arxiv_by_title(title)

    assert match["arxiv_id"] == "2609.00002v2"
    assert len(web.calls) == 2 and "+OR+" in web.calls[1]


@pytest.mark.parametrize("found_title", [
    "RepoReasoner 2: Evaluating File-Level Code Reasoning Ability of Short-Context Language Models",
    "A Survey of Repository-Level Code Reasoning",
])
def test_similar_but_different_title_is_not_a_match(web, no_wait, found_title):
    web.routes["export.arxiv.org"] = atom(("2601.00009v1", found_title))
    assert academic_api.find_arxiv_by_title(REPO_TITLE) is None


def test_short_title_must_match_exactly(web, no_wait):
    web.routes["export.arxiv.org"] = atom(("2606.17551v1", "Reversal Q-Learning"), ("2606.00003v1", "Reversed Q-Learning"))
    assert academic_api.find_arxiv_by_title("Reversal Q-Learning")["arxiv_id"] == "2606.17551v1"
    web.routes["export.arxiv.org"] = atom(("2606.00003v1", "Reversed Q-Learning"))
    assert academic_api.find_arxiv_by_title("Reversal Q-Learning") is None


@pytest.mark.parametrize("answer", [FakeResponse(429), ConnectionError("timed out"), FakeResponse(200, b"not xml")])
def test_arxiv_not_answering_means_no_match_and_no_second_request(web, no_wait, answer):
    web.routes["export.arxiv.org"] = answer
    assert academic_api.find_arxiv_by_title(REPO_TITLE) is None
    assert len(web.calls) == 1


def test_title_too_short_to_search_makes_no_request(web, no_wait):
    assert academic_api.find_arxiv_by_title("Untitled") is None
    assert academic_api.find_arxiv_by_title("On AI") is None
    assert web.calls == []


def test_title_searches_are_spaced_out(web, monkeypatch):
    monkeypatch.setattr(academic_api, "ARXIV_SEARCH_MIN_INTERVAL", 0.2)
    monkeypatch.setattr(academic_api, "_arxiv_last_search", 0.0)
    web.routes["export.arxiv.org"] = atom()
    import time
    start = time.monotonic()
    academic_api.find_arxiv_by_title(REPO_TITLE)      # two requests: all words, then any word
    assert len(web.calls) == 2
    assert time.monotonic() - start >= 0.2
