"""
Tests for reading paper links out of a Google Scholar alert email.

Scholar wraps the alert's keywords in <b>. Stripping each piece of text on its own glued
the neighbouring words together ("DeepReinforcement Learningfor"), which broke every
lookup of a paper by its title.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gmail_fetcher


def titles(html):
    return [link["title"] for link in gmail_fetcher.extract_links_from_html(html)]


def test_words_around_a_bold_keyword_keep_their_spaces():
    html = ('<a href="https://arxiv.org/abs/2607.11720">Deep <b>Reinforcement Learning</b> for '
            'Risk-Aware <b>Portfolio</b> Management</a>')
    assert titles(html) == ["Deep Reinforcement Learning for Risk-Aware Portfolio Management"]


def test_punctuation_next_to_a_bold_keyword_gets_no_extra_space():
    html = ('<a href="https://x.org/1">Multi-<b>Agent</b> Systems (<b>RL</b>): '
            'A <b>Survey</b>.</a>')
    assert titles(html) == ["Multi-Agent Systems (RL): A Survey."]


def test_line_breaks_and_runs_of_spaces_collapse_to_one_space():
    html = '<a href="https://x.org/2">\n   Rough   <b>Path\nSignatures</b>\n in Finance  </a>'
    assert titles(html) == ["Rough Path Signatures in Finance"]


def test_link_without_text_is_untitled():
    assert titles('<a href="https://x.org/3"> </a>') == ["Untitled Resource"]
