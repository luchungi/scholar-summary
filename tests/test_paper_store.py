import os
import time
from pathlib import Path

import pymupdf
import pytest

import config
import paper_retriever
import paper_store


def make_pdf(path: Path, page1: str, page3: str = "") -> Path:
    doc = pymupdf.open()
    for text in (page1, "Second page body.", page3):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture(autouse=True)
def isolated_index(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_PDF_INDEX", str(tmp_path / "index" / "user_pdfs.json"))
    paper_store._scan_cache.clear()


def test_key_is_lowercase_doi_shared_by_link_forms():
    abs_key = paper_store.paper_key("https://dl.acm.org/doi/abs/10.1145/3858063.3858848")
    full_key = paper_store.paper_key("https://dl.acm.org/doi/full/10.1145/3858063.3858848")
    assert abs_key == full_key == "10.1145/3858063.3858848"
    assert paper_store.paper_key("https://x.org/doi/10.1007/S10479-025-1") == "10.1007/s10479-025-1"


def test_key_without_doi_is_url_hash():
    key = paper_store.paper_key("https://www.sciencedirect.com/science/article/pii/S0957417425012345")
    assert key.startswith("url-") and len(key) == 20


def test_register_and_lookup_then_missing_file(tmp_path):
    pdf = make_pdf(tmp_path / "3858063.3858848.pdf", "doi 10.1145/3858063.3858848")
    paper_store.register("https://dl.acm.org/doi/full/10.1145/3858063.3858848", str(pdf), "T")
    # Another link form of the same paper finds it.
    assert paper_store.pdf_for("https://dl.acm.org/doi/pdf/10.1145/3858063.3858848") == str(pdf.resolve())
    pdf.unlink()
    assert paper_store.pdf_for("https://dl.acm.org/doi/pdf/10.1145/3858063.3858848") is None
    assert paper_store.pdf_for("https://dl.acm.org/doi/pdf/10.1145/9999") is None


def test_match_by_doi_in_first_pages(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", "Paper A\nhttps://doi.org/10.1145/3858063.3858848\nAbstract ...")
    # DOI broken over two lines still matches.
    b = make_pdf(tmp_path / "b.pdf", "Paper B\nhttps://doi.org/10.1145/3858063.\n3858835")
    # Only on page 3: not read.
    c = make_pdf(tmp_path / "c.pdf", "Paper C", page3="10.1145/3858063.3859363")
    # A longer DOI that starts with a wanted one does not match it.
    d = make_pdf(tmp_path / "d.pdf", "Paper D 10.1145/38081312 and 10.1145/3808131.3808200")
    wanted = ["10.1145/3858063.3858848", "10.1145/3858063.3858835", "10.1145/3858063.3859363", "10.1145/3808131"]
    matches = paper_store.match_pdfs([a, b, c, d], wanted)
    assert matches == {"10.1145/3858063.3858848": a, "10.1145/3858063.3858835": b}


def test_doi_followed_by_text_still_matches(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", "DOI: 10.1145/3808131.\nAbstract follows")
    assert paper_store.match_pdfs([a], ["10.1145/3808131"]) == {"10.1145/3808131": a}


def test_pdf_naming_two_wanted_dois_is_ambiguous(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", "10.1145/1111111 and 10.1145/2222222")
    assert paper_store.match_pdfs([a], ["10.1145/1111111", "10.1145/2222222"]) == {}


def test_recent_pdfs_top_level_and_age(tmp_path):
    new = make_pdf(tmp_path / "new.PDF", "x")
    old = make_pdf(tmp_path / "old.pdf", "x")
    week_ago = time.time() - 8 * 86400
    os.utime(old, (week_ago, week_ago))
    (tmp_path / "sub").mkdir()
    make_pdf(tmp_path / "sub" / "nested.pdf", "x")
    (tmp_path / "notes.txt").write_text("x")
    assert paper_store.recent_pdfs(str(tmp_path), 7) == [new]
    assert paper_store.recent_pdfs(str(tmp_path / "missing"), 7) == []


def test_retriever_reads_user_pdf_first(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "p.pdf", "Making Tail Constraints Bind\n10.1145/3858063.3858848\n" + "Body text. " * 50)
    url = "https://dl.acm.org/doi/full/10.1145/3858063.3858848"
    paper_store.register(url, str(pdf))

    def no_network(*a, **k):
        raise AssertionError("the network must not be used when the user's PDF exists")
    monkeypatch.setattr(paper_retriever, "_retrieve_from_site", no_network)
    import academic_api
    monkeypatch.setattr(academic_api, "get_paper_by_academic_api", no_network)

    result = paper_retriever.retrieve_paper(url)
    assert result["coverage"] == "full"
    assert result["source"] == "pdf"
    assert result["user_pdf"] == "p.pdf"
    assert "Making Tail Constraints Bind" in result["text"]
