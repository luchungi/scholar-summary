"""
Tests for the EndNote .enw export path (decisions 0009 and 0010).

All tests here are offline: they exercise the reference-type resolver, the reference
rules schema and the .enw serializer, none of which touch the network.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import citation_service as cs


@pytest.fixture(autouse=True)
def _clear_rules_cache():
    """Each test reads the real url/reference_rules.json from a clean cache."""
    cs._REFERENCE_RULES_CACHE = None
    yield
    cs._REFERENCE_RULES_CACHE = None


# --- the reference rules schema itself ---

def test_reference_rules_file_loads():
    rules = cs.load_reference_rules()
    assert rules.get("endnote_types"), "endnote_types vocabulary must be present"
    assert rules.get("default_type") in rules["endnote_types"]


def test_every_mapped_type_is_a_valid_endnote_type():
    """
    The invariant that the 'Preprint' bug (DE-003) violated: every reference type the
    exporter can emit must exist in EndNote's vocabulary, or EndNote silently
    substitutes its own default.
    """
    rules = cs.load_reference_rules()
    vocabulary = set(rules["endnote_types"])

    for crossref_type, endnote_type in rules["crossref_type_map"].items():
        assert endnote_type in vocabulary, f"crossref_type_map[{crossref_type}]"

    for host, entry in rules["host_overrides"].items():
        if entry.get("ref_type"):
            assert entry["ref_type"] in vocabulary, f"host_overrides[{host}]"

    for host, entry in rules["preprint_venues"].items():
        if entry.get("ref_type"):
            assert entry["ref_type"] in vocabulary, f"preprint_venues[{host}]"

    for key in ("periodical_types", "secondary_title_types"):
        for endnote_type in rules.get(key, []):
            assert endnote_type in vocabulary, f"{key}: {endnote_type}"


def test_preprint_is_not_a_valid_endnote_type():
    """Guards the specific regression: 'Preprint' is not in EndNote 21's vocabulary."""
    assert "Preprint" not in cs.load_reference_rules()["endnote_types"]


# --- type validation ---

def test_validate_rejects_unknown_type_and_falls_back(capsys):
    assert cs.validate_ref_type("Preprint") == "Journal Article"
    assert "not in the EndNote reference type vocabulary" in capsys.readouterr().out


def test_validate_passes_known_types_through():
    for known in ("Journal Article", "Conference Paper", "Thesis", "Report"):
        assert cs.validate_ref_type(known) == known


def test_validate_handles_empty_input():
    assert cs.validate_ref_type(None) == "Journal Article"
    assert cs.validate_ref_type("   ") == "Journal Article"


# --- crossref type mapping ---

def test_crossref_posted_content_is_not_conference_proceedings():
    """Preprints came back from Crossref as 'Conference Proceedings' before 0009."""
    assert cs.map_crossref_type("posted-content") == "Journal Article"


@pytest.mark.parametrize("crossref_type,expected", [
    ("journal-article", "Journal Article"),
    ("proceedings-article", "Conference Paper"),
    ("dissertation", "Thesis"),
    ("book-chapter", "Book Section"),
    ("report", "Report"),
])
def test_crossref_type_map(crossref_type, expected):
    assert cs.map_crossref_type(crossref_type) == expected


def test_unknown_crossref_type_falls_back_to_default():
    assert cs.map_crossref_type("component") == "Journal Article"
    assert cs.map_crossref_type(None) == "Journal Article"


# --- host lookup ---

def test_host_lookup_matches_parent_domain():
    """'search.proquest.com' must match the 'proquest.com' override entry."""
    rules = cs.load_reference_rules()
    entry = cs.lookup_host_entry(rules["host_overrides"], "https://search.proquest.com/x/1")
    assert entry and entry["ref_type"] == "Thesis"


def test_host_lookup_strips_www():
    rules = cs.load_reference_rules()
    entry = cs.lookup_host_entry(rules["preprint_venues"], "https://www.researchsquare.com/article/rs-1")
    assert entry and entry["label"] == "Research Square"


def test_host_lookup_returns_none_for_unknown_host():
    rules = cs.load_reference_rules()
    assert cs.lookup_host_entry(rules["host_overrides"], "https://example.com/paper") is None


# --- preprint journal strings ---

def test_arxiv_journal_string_keeps_version():
    result = cs.build_preprint_journal("https://arxiv.org/abs/2605.15156v2", arxiv_id="2605.15156v2")
    assert result["journal"] == "arXiv preprint arXiv:2605.15156v2"
    assert result["ref_type"] == "Journal Article"


def test_non_arxiv_preprint_uses_doi():
    result = cs.build_preprint_journal(
        "https://www.researchsquare.com/article/rs-9896014/latest.pdf",
        doi="10.21203/rs.3.rs-9896014/v1",
    )
    assert result["journal"] == "Research Square preprint 10.21203/rs.3.rs-9896014/v1"


def test_preprint_without_identifier_falls_back_to_label():
    result = cs.build_preprint_journal("https://biorxiv.org/content/x")
    assert result["journal"] == "bioRxiv preprint"


def test_non_preprint_host_has_no_journal_template():
    assert cs.build_preprint_journal("https://www.nature.com/articles/s41586") is None


# --- finalize_reference_fields ---

def test_openreview_override_applies_when_crossref_absent():
    meta = {"url": "https://openreview.net/forum?id=abc", "ref_type": "Journal Article"}
    assert cs.finalize_reference_fields(meta, meta["url"])["ref_type"] == "Conference Paper"


def test_crossref_type_wins_over_host_override():
    """A Crossref type describes the work; an override is only a venue-wide guess."""
    meta = {
        "url": "https://dl.acm.org/doi/10.1145/1234",
        "ref_type": "Journal Article",
        "source": "crossref",
    }
    assert cs.finalize_reference_fields(meta, meta["url"])["ref_type"] == "Journal Article"


def test_finalize_validates_invalid_type():
    meta = {"url": "https://arxiv.org/abs/2605.15156v2", "ref_type": "Preprint"}
    assert cs.finalize_reference_fields(meta, meta["url"])["ref_type"] == "Journal Article"


def test_finalize_adds_preprint_journal_for_non_arxiv_host():
    meta = {
        "url": "https://www.preprints.org/manuscript/202606.1491",
        "doi": "10.20944/preprints202606.1491.v1",
        "ref_type": "Journal Article",
    }
    out = cs.finalize_reference_fields(meta, meta["url"])
    assert out["journal"] == "Preprints.org preprint 10.20944/preprints202606.1491.v1"


def test_finalize_does_not_overwrite_a_real_journal():
    meta = {
        "url": "https://www.biorxiv.org/content/10.1101/2024.01.01",
        "journal": "Nature Methods",
        "doi": "10.1101/2024.01.01",
        "ref_type": "Journal Article",
    }
    assert cs.finalize_reference_fields(meta, meta["url"])["journal"] == "Nature Methods"


# --- .enw serialization ---

ARXIV_META = {
    "title": "GROMM: Generative Risk-neutral Option Market Models",
    "authors": ["Wiese, Magnus", "Horvath, Blanka"],
    "journal": "arXiv preprint arXiv:2605.15156v2",
    "year": "2026",
    "doi": None,
    "url": "https://arxiv.org/abs/2605.15156v2",
    "abstract": "We propose a generative model for option markets.",
    "ref_type": "Journal Article",
}


def test_enw_omits_abstract_and_research_notes():
    enw = cs.generate_enw_content(ARXIV_META, pdf_local_path="/tmp/Wiese_2026_GROMM.pdf")
    assert "%X" not in enw, "abstract must not be written (decision 0010)"
    assert "%<" not in enw, "research notes must not be written (DE-004)"


def test_enw_attachment_uses_only_the_file_attachment_tag():
    enw = cs.generate_enw_content(ARXIV_META, pdf_local_path="/tmp/Wiese_2026_GROMM.pdf")
    assert "%> /tmp/Wiese_2026_GROMM.pdf" in enw
    assert enw.count("/tmp/Wiese_2026_GROMM.pdf") == 1


def test_enw_journal_article_uses_j_not_b():
    enw = cs.generate_enw_content(ARXIV_META)
    assert "%J arXiv preprint arXiv:2605.15156v2" in enw
    assert "%B" not in enw


def test_enw_conference_paper_uses_b_not_j():
    meta = dict(ARXIV_META, ref_type="Conference Paper", journal="NeurIPS 2026")
    enw = cs.generate_enw_content(meta)
    assert "%B NeurIPS 2026" in enw
    assert "%J" not in enw


def test_enw_invalid_type_is_corrected_in_output():
    enw = cs.generate_enw_content(dict(ARXIV_META, ref_type="Preprint"))
    assert enw.startswith("%0 Journal Article")
    assert "Preprint\n" not in enw


def test_enw_golden_output():
    assert cs.generate_enw_content(ARXIV_META, pdf_local_path="/tmp/Wiese_2026_GROMM.pdf") == (
        "%0 Journal Article\n"
        "%T GROMM: Generative Risk-neutral Option Market Models\n"
        "%A Wiese, Magnus\n"
        "%A Horvath, Blanka\n"
        "%J arXiv preprint arXiv:2605.15156v2\n"
        "%D 2026\n"
        "%U https://arxiv.org/abs/2605.15156v2\n"
        "%> /tmp/Wiese_2026_GROMM.pdf\n"
        "\n"
    )


def test_combined_enw_separates_records_with_a_blank_line():
    combined = cs.generate_combined_enw([ARXIV_META, dict(ARXIV_META, title="Second Paper")])
    assert combined.count("%0 Journal Article") == 2
    assert "\n\n%0" in combined
