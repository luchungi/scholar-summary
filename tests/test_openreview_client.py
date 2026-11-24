import importlib.util
import io
import json
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
import pytest
import requests
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import academic_api
import config
import openreview_client as orc
import paper_retriever as pr
import paper_store
from backend import main as backend_main
from backend import pdf_service
from backend.models import Paper

EMAIL = "reader@example.org"
PASSWORD = "S3cret pass=word #1 "  # the spaces and "=" must survive the file format
TOKEN = "fake-token-abc123"
NOTE = "AbC_1-xyz"
URL = f"https://openreview.net/forum?id={NOTE}"
LONG_ABSTRACT = "An abstract long enough for the relevance gate to read. " * 6


def make_pdf(text="Paper body text from the OpenReview API."):
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), text)
        return document.tobytes()


class Response:
    def __init__(self, status_code=200, body=None, content=None):
        self.status_code = status_code
        self._body = body
        self.content = content if content is not None else json.dumps(body or {}).encode()
        self.headers = {"Content-Type": "application/pdf" if content else "application/json"}

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


def v2_note(pdf=True, abstract=LONG_ABSTRACT):
    content = {"title": {"value": "A Title From OpenReview"}, "abstract": {"value": abstract}}
    if pdf:
        content["pdf"] = {"value": "/pdf/abc.pdf"}
    return Response(200, {"notes": [{"id": NOTE, "content": content}]})


NOT_FOUND = Response(404, {"name": "NotFoundError"})


class FakeApi:
    """Stands in for the network. `responses` maps a full URL to a response or a list of them."""

    def __init__(self):
        self.login = Response(200, {"token": TOKEN})
        self.login_delay = 0
        self.responses = {}
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        time.sleep(self.login_delay)
        if isinstance(self.login, Exception):
            raise self.login
        return self.login

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        answer = self.responses.get(url, NOT_FOUND)
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    fake.responses[f"{orc.API_V2}/notes"] = v2_note()
    fake.responses[f"{orc.API_V2}/pdf"] = Response(200, content=make_pdf())
    monkeypatch.setattr(orc.requests, "post", fake.post)
    monkeypatch.setattr(orc.requests, "get", fake.get)
    monkeypatch.setattr(academic_api, "find_arxiv_by_title", lambda title: None)
    monkeypatch.setattr(paper_store, "pdf_for", lambda url: None)
    return fake


@pytest.fixture
def login_file(tmp_path, monkeypatch):
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    path = folder / "openreview.env"
    path.write_text(f"OPENREVIEW_EMAIL={EMAIL}\nOPENREVIEW_PASSWORD={PASSWORD}\n")
    path.chmod(0o600)
    monkeypatch.setattr(config, "OPENREVIEW_CREDENTIALS_PATH", path)
    return path


@pytest.mark.parametrize("url,expected", [
    ("https://openreview.net/forum?id=O1QyK9MzL5", "O1QyK9MzL5"),
    ("https://openreview.net/pdf?id=56zEVqIFMF", "56zEVqIFMF"),
    ("https://www.openreview.net/forum?id=a_b-c&noteId=zzz", "a_b-c"),
    ("http://OpenReview.net/pdf/?id=abc", "abc"),
    ("https://openreview.net/profile?id=~Some_Person1", None),
    ("https://openreview.net/forum", None),
    ("https://openreview.net/forum?id=../../login", None),
    ("https://openreview.net.evil.org/forum?id=abc", None),
    ("https://evil.org/openreview.net/forum?id=abc", None),
    ("not a url", None),
    (None, None),
])
def test_only_openreview_paper_links_are_recognised(url, expected):
    assert orc.extract_forum_id(url) == expected


def test_no_login_file_leaves_retrieval_as_it_was(api):
    assert orc.fetch_paper(URL) is None
    assert api.posts == [] and api.gets == []


def test_other_sites_never_touch_the_login(api, login_file):
    assert orc.fetch_paper("https://arxiv.org/abs/2401.00001") is None
    assert api.posts == [] and api.gets == []


def test_paper_is_read_through_the_api(api, login_file):
    result = pr.retrieve_paper(URL)
    assert result["coverage"] == "full"
    assert result["source"] == "pdf"
    assert result["title"] == "A Title From OpenReview"
    assert "Paper body text" in result["text"]
    assert [url for url, _ in api.gets] == [f"{orc.API_V2}/notes", f"{orc.API_V2}/pdf"]


def test_password_goes_only_to_the_login_endpoint_without_redirects(api, login_file):
    orc.fetch_paper(URL)
    assert len(api.posts) == 1
    url, kwargs = api.posts[0]
    assert url == "https://api2.openreview.net/login"
    assert kwargs["json"] == {"id": EMAIL, "password": PASSWORD, "expiresIn": orc.TOKEN_SECONDS}
    assert kwargs["allow_redirects"] is False
    for url, kwargs in api.gets:
        assert url.startswith(("https://api2.openreview.net/", "https://api.openreview.net/"))
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"] == {"Cookie": f"openreview.accessToken={TOKEN}"}
        assert PASSWORD not in repr(kwargs)


def test_a_redirected_login_is_not_followed(api, login_file):
    api.login = Response(302, {})
    result = orc.fetch_paper(URL)
    assert result["pdf"] is None
    assert "HTTP 302" in result["reason"]
    assert len(api.posts) == 1 and api.gets == []


@pytest.mark.parametrize("file_mode,folder_mode", [(0o640, 0o700), (0o604, 0o700), (0o600, 0o750), (0o600, 0o705)])
def test_a_login_others_could_read_is_refused(api, login_file, file_mode, folder_mode):
    login_file.chmod(file_mode)
    login_file.parent.chmod(folder_mode)
    result = orc.fetch_paper(URL)
    assert "only your user" in result["reason"]
    assert api.posts == []


def test_a_symlinked_login_file_is_refused(api, login_file, tmp_path, monkeypatch):
    link = login_file.parent / "link.env"
    link.symlink_to(login_file)
    monkeypatch.setattr(config, "OPENREVIEW_CREDENTIALS_PATH", link)
    assert "symlink" in orc.fetch_paper(URL)["reason"]
    assert api.posts == []


def test_a_malformed_login_file_is_refused(api, login_file):
    login_file.write_text("OPENREVIEW_EMAIL=only@example.org\n")
    assert "expected format" in orc.fetch_paper(URL)["reason"]
    assert api.posts == []


def test_parallel_papers_share_one_login(api, login_file):
    api.login_delay = 0.05
    api.responses[f"{orc.API_V2}/notes"] = v2_note()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(orc.fetch_paper, [URL] * 6))
    assert all(result["pdf"] for result in results)
    assert len(api.posts) == 1


def test_an_expired_token_gets_one_new_login(api, login_file):
    api.responses[f"{orc.API_V2}/notes"] = [Response(401, {"name": "TokenExpiredError"}), v2_note()]
    assert orc.fetch_paper(URL)["pdf"]
    assert len(api.posts) == 2


def test_a_token_refused_twice_stops(api, login_file):
    api.responses[f"{orc.API_V2}/notes"] = [Response(401, {}), Response(401, {})]
    result = orc.fetch_paper(URL)
    assert result["reason"] == "OpenReview refused the login token"
    assert len(api.posts) == 2 and len(api.gets) == 2


def test_a_token_near_its_expiry_is_replaced(api, login_file, monkeypatch):
    orc.fetch_paper(URL)
    monkeypatch.setattr(orc, "_token_expires", time.monotonic() + orc.TOKEN_MARGIN_SECONDS - 1)
    orc.fetch_paper(URL)
    assert len(api.posts) == 2


def test_a_rejected_login_stops_until_the_next_run(api, login_file):
    api.login = Response(400, {"name": "LoginError"})
    first = orc.fetch_paper(URL)
    second = orc.fetch_paper(URL)
    assert "check the email and password" in first["reason"]
    assert second["reason"] == first["reason"]
    assert len(api.posts) == 1

    orc.reset_login_failure()
    api.login = Response(200, {"token": TOKEN})
    assert orc.fetch_paper(URL)["pdf"]
    assert len(api.posts) == 2


def test_a_login_blocked_by_the_challenge_stays_blocked_for_every_paper(api, login_file):
    api.login = Response(403, {"name": "ChallengeRequiredError"})
    assert orc.fetch_paper(URL)["blocked"] is True
    assert orc.fetch_paper(URL)["blocked"] is True
    assert len(api.posts) == 1


def test_a_login_needing_multi_factor_is_explained(api, login_file):
    api.login = Response(200, {"mfaPending": True})
    assert "multi-factor" in orc.fetch_paper(URL)["reason"]


def test_older_papers_fall_back_to_api_v1(api, login_file):
    api.responses[f"{orc.API_V2}/notes"] = NOT_FOUND
    api.responses[f"{orc.API_V1}/notes"] = Response(200, {"notes": [{"id": NOTE, "content": {
        "title": "A V1 Title", "abstract": LONG_ABSTRACT, "pdf": "/pdf/old.pdf"}}]})
    api.responses[f"{orc.API_V1}/pdf"] = Response(200, content=make_pdf("Old paper body."))
    result = pr.retrieve_paper(URL)
    assert result["coverage"] == "full"
    assert result["title"] == "A V1 Title"
    assert "Old paper body" in result["text"]
    assert len(api.posts) == 1


def test_a_paper_on_neither_api_fails_with_a_reason(api, login_file):
    api.responses[f"{orc.API_V2}/notes"] = NOT_FOUND
    result = pr.retrieve_paper(URL)
    assert result["coverage"] == "failed"
    assert result["reason"] == "OpenReview has no paper with this ID"


def test_a_private_paper_keeps_its_reason_and_does_not_try_v1(api, login_file):
    api.responses[f"{orc.API_V2}/notes"] = Response(403, {"name": "ForbiddenError"})
    result = pr.retrieve_paper(URL)
    assert result["coverage"] == "failed"
    assert "not public to your account" in result["reason"]
    assert len(api.gets) == 1


def test_a_challenge_while_logged_in_is_reported_as_blocked(api, login_file):
    api.responses[f"{orc.API_V2}/notes"] = Response(403, {"name": "ChallengeRequiredError"})
    result = pr.retrieve_paper(URL)
    assert result["coverage"] == "blocked"
    assert "even when logged in" in result["reason"]


def test_rate_limit_is_not_retried(api, login_file):
    api.responses[f"{orc.API_V2}/notes"] = Response(429, {"name": "RateLimitError"})
    result = orc.fetch_paper(URL)
    assert "rate limit" in result["reason"]
    assert len(api.gets) == 1


def test_a_paper_without_a_pdf_keeps_its_abstract_for_the_gate(api, login_file):
    api.responses[f"{orc.API_V2}/notes"] = v2_note(pdf=False)
    result = pr.retrieve_paper(URL)
    assert result["coverage"] == "failed"
    assert result["reason"] == "OpenReview lists no PDF for this paper"
    assert result["abstract"] == LONG_ABSTRACT
    assert result["title"] == "A Title From OpenReview"
    assert result["text"] is None
    assert len(api.gets) == 1


def test_an_html_answer_is_not_taken_for_the_pdf(api, login_file):
    api.responses[f"{orc.API_V2}/pdf"] = Response(200, content=b"<html>Verifying your browser</html>")
    result = pr.retrieve_paper(URL)
    assert result["coverage"] == "failed"
    assert result["reason"] == "OpenReview did not return a PDF"


def test_when_the_api_fails_the_arxiv_copy_is_used_and_the_site_is_not_fetched(api, login_file, monkeypatch):
    api.responses[f"{orc.API_V2}/pdf"] = Response(500, {})
    api.responses["https://arxiv.org/pdf/2401.00001.pdf"] = Response(200, content=make_pdf("The arXiv copy."))
    searched = []

    def find(title):
        searched.append(title)
        return {"arxiv_id": "2401.00001", "title": title, "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf"}

    monkeypatch.setattr(academic_api, "find_arxiv_by_title", find)
    monkeypatch.setattr(pr, "_retrieve_from_site", lambda *a: pytest.fail("the challenged site must not be fetched"))
    result = pr.retrieve_paper(URL, title="Alert Title")
    assert result["coverage"] == "full"
    assert "The arXiv copy" in result["text"]
    assert searched == ["A Title From OpenReview"]
    assert "HTTP 500" in result["note"]


def test_a_pdf_the_user_downloaded_still_comes_first(api, login_file, tmp_path, monkeypatch):
    user_pdf = tmp_path / "mine.pdf"
    user_pdf.write_bytes(make_pdf("The user's own copy."))
    monkeypatch.setattr(paper_store, "pdf_for", lambda url: str(user_pdf))
    assert "own copy" in pr.retrieve_paper(URL)["text"]
    assert api.posts == [] and api.gets == []


@pytest.mark.parametrize("failure", ["login", "notes", "pdf"])
def test_network_errors_never_expose_the_login(api, login_file, capsys, failure):
    secret_error = requests.ConnectionError(f"failed with {PASSWORD} and {TOKEN}")
    if failure == "login":
        api.login = secret_error
    else:
        api.responses[f"{orc.API_V2}/{failure}"] = secret_error
    result = pr.retrieve_paper(URL)
    printed = capsys.readouterr()
    for text in (repr(result), printed.out, printed.err):
        assert PASSWORD not in text and PASSWORD.strip() not in text
        assert TOKEN not in text
    assert "ConnectionError" in result["reason"]


def test_success_prints_no_login(api, login_file, capsys):
    result = pr.retrieve_paper(URL)
    printed = capsys.readouterr()
    for text in (repr({k: v for k, v in result.items() if k != "text"}), printed.out, printed.err):
        assert EMAIL not in text and PASSWORD.strip() not in text and TOKEN not in text


def test_the_login_is_not_put_in_the_environment(api, login_file):
    orc.fetch_paper(URL)
    assert not any(PASSWORD.strip() in value or TOKEN in value for value in os.environ.values())


def test_setup_script_writes_where_the_app_reads(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "setup_openreview.py"
    spec = importlib.util.spec_from_file_location("setup_openreview", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.undo()  # compare with the real path, not the test's isolated one
    assert module.CREDENTIALS_PATH == config.OPENREVIEW_CREDENTIALS_PATH


def test_setup_script_output_round_trips_through_the_client(api, tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "setup_openreview.py"
    spec = importlib.util.spec_from_file_location("setup_openreview", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "fresh" / "openreview.env"
    module.write_credentials(target, EMAIL, PASSWORD)
    monkeypatch.setattr(config, "OPENREVIEW_CREDENTIALS_PATH", target)
    assert orc._load_credentials() == (EMAIL, PASSWORD)


# --- PDF and EndNote exports -----------------------------------------------------------

PUBLIC_PDF_LINK = f"https://openreview.net/pdf?id={NOTE}"


@pytest.fixture
def session(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(backend_main, "resolve_paper_metadata", lambda url, title, report_path: {
        "title": title, "authors": ["Doe, Jane"], "year": "2026", "journal": "NeurIPS",
        "url": url, "ref_type": "Conference Paper",
    })
    with Session(engine) as db:
        db.add(Paper(id=1, title="A Title From OpenReview", url=URL, status="success"))
        db.commit()
        yield db


def test_export_link_needs_no_network_and_holds_no_credentials(api, login_file):
    assert pdf_service.resolve_pdf_url(f"{URL}&noteId=reply") == PUBLIC_PDF_LINK
    assert api.posts == [] and api.gets == []


def test_export_prefers_a_pdf_the_user_downloaded(api, login_file, monkeypatch):
    monkeypatch.setattr(paper_store, "pdf_for", lambda url: "/tmp/mine.pdf")
    assert pdf_service.resolve_pdf_url(URL) == "file:///tmp/mine.pdf"


def test_export_download_goes_through_the_api(api, login_file):
    assert pdf_service.download_pdf_bytes(PUBLIC_PDF_LINK).startswith(b"%PDF-")
    assert [url for url, _ in api.gets] == [f"{orc.API_V2}/notes", f"{orc.API_V2}/pdf"]
    assert PUBLIC_PDF_LINK not in [url for url, _ in api.gets]


def test_export_download_rejects_an_answer_that_is_not_a_pdf(api, login_file):
    api.responses[f"{orc.API_V2}/pdf"] = Response(200, content=b"<html>Verifying your browser</html>")
    assert pdf_service.download_pdf_bytes(PUBLIC_PDF_LINK) is None


def test_export_without_a_login_uses_the_public_link_as_before(api):
    api.responses[PUBLIC_PDF_LINK] = Response(200, content=make_pdf())
    assert pdf_service.download_pdf_bytes(PUBLIC_PDF_LINK).startswith(b"%PDF-")
    assert api.posts == []
    assert [url for url, _ in api.gets] == [PUBLIC_PDF_LINK]


def test_single_pdf_endpoint_returns_the_file(api, login_file, session):
    response = backend_main.download_paper_pdf(1, session)
    assert response.body.startswith(b"%PDF-")
    assert response.media_type == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]


def test_single_pdf_endpoint_reports_a_failure_instead_of_a_broken_file(api, login_file, session):
    api.responses[f"{orc.API_V2}/pdf"] = Response(403, {"name": "ForbiddenError"})
    with pytest.raises(HTTPException) as failure:
        backend_main.download_paper_pdf(1, session)
    assert failure.value.status_code == 502


def test_bulk_export_includes_the_pdf(api, login_file, session):
    response = backend_main.bulk_export_reports(backend_main.BulkExportRequest(paper_ids=[1]), session)
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        names = archive.namelist()
        pdf_names = [name for name in names if name.endswith(".pdf")]
        assert len(pdf_names) == 1
        assert archive.read(pdf_names[0]).startswith(b"%PDF-")
        assert f"%> {pdf_names[0]}" in archive.read("citations_all.enw").decode()
        for name in names:
            content = archive.read(name)
            assert PASSWORD.strip().encode() not in content and TOKEN.encode() not in content


def test_one_click_endnote_export_saves_and_attaches_the_pdf(api, login_file, session, tmp_path, monkeypatch):
    monkeypatch.setattr(backend_main.Path, "home", lambda: tmp_path)
    opened = []
    monkeypatch.setattr(backend_main.subprocess, "Popen", lambda command: opened.append(command))
    result = backend_main.endnote_export(backend_main.EndNoteExportRequest(paper_ids=[1]), session)
    assert result["with_pdf_count"] == 1 and result["citation_only_count"] == 0
    saved = list(Path(result["batch_dir"]).glob("*.pdf"))
    assert len(saved) == 1 and saved[0].read_bytes().startswith(b"%PDF-")
    assert str(saved[0].resolve()) in Path(result["enw_path"]).read_text()
    assert len(opened) == 1


def test_each_export_may_retry_a_failed_login_once(api, login_file, session):
    api.login = Response(400, {"name": "LoginError"})
    request = backend_main.BulkExportRequest(paper_ids=[1])
    backend_main.bulk_export_reports(request, session)
    assert len(api.posts) == 1
    backend_main.bulk_export_reports(request, session)
    assert len(api.posts) == 2
