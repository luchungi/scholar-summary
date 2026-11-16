r"""
Tests for math_delimiters.normalize_math_delimiters.

The frontend's remark-math only renders $...$ and $$...$$ (with the $$ fences alone on
their lines), so every report is rewritten into that form before it is saved. The inputs
below are the shapes actually found in saved qwen3.8 and gemma-4 reports. All offline.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import agent
from math_delimiters import normalize_math_delimiters


def norm(text):
    return normalize_math_delimiters(text)[0]


def test_inline_parens_become_single_dollars():
    out, stats = normalize_math_delimiters(r"where \(M\) is the number and \( k = 0 \) too")
    assert out == "where $M$ is the number and $k = 0$ too"
    assert (stats.inline, stats.display, stats.promoted, stats.unbalanced) == (2, 0, 0, 0)


def test_display_brackets_become_fenced_dollars():
    # The lone "=" line is what turned the line above it into a heading before the fix.
    src = "The loss is\n\\[\n\\mathcal{L}(\\theta)\n=\n\\sum_{k=0}^{K} w_k\n\\]\ndone"
    out, stats = normalize_math_delimiters(src)
    assert out == "The loss is\n$$\n\\mathcal{L}(\\theta)\n=\n\\sum_{k=0}^{K} w_k\n$$\ndone"
    assert stats.display == 1


def test_display_inside_list_item_keeps_its_indentation():
    src = "2. **Claim.** text\n   \\[\n   a = b,\n   \\]\n   but more"
    assert norm(src) == "2. **Claim.** text\n   $$\n   a = b,\n   $$\n   but more"


def test_display_body_is_reindented_to_the_list_item():
    src = "1. Item\n   \\[\na = b\n   \\]"
    assert norm(src) == "1. Item\n   $$\n   a = b\n   $$"


def test_display_written_inside_a_sentence_is_broken_out():
    assert norm(r"so that \[ a = b \] holds") == "so that\n$$\na = b\n$$\nholds"


def test_display_on_a_list_marker_line():
    assert norm("- \\[ a = b \\]\n- next") == "- $$\n  a = b\n  $$\n- next"


def test_trailing_punctuation_moves_into_the_equation():
    assert norm("\\[\na = b\n\\].\nNext") == "$$\na = b.\n$$\nNext"


def test_single_line_double_dollars_are_promoted_to_a_block():
    out, stats = normalize_math_delimiters("Text\n\n$$\\frac{d}{dt} Y = A Y$$\n\nmore")
    assert out == "Text\n\n$$\n\\frac{d}{dt} Y = A Y\n$$\n\nmore"
    assert stats.promoted == 1


def test_double_dollars_with_content_on_the_fence_lines_are_fixed():
    assert norm("$$ a = b\n+ c $$") == "$$\na = b\n+ c\n$$"


@pytest.mark.parametrize("text", [
    "Text\n\n$$\nx = y\n$$\n\nmore",                     # already canonical
    "1. Item\n   $$\n   x = y\n   $$\n   more",           # canonical inside a list
    "inline $x$ and currency \\$1.50 stay",
    "the value $$x$$ sits mid-sentence",                  # ambiguous: left as written
    "cited in \\[12\\] and \\[3, 4\\]",                   # escaped citation brackets
    "matrix rows a \\\\[2pt] b",                          # LaTeX row spacing, not a delimiter
    "code `\\(x\\)` and `\\[y\\]` stays",
    "```latex\n\\[\nx\n\\]\n```\n",
    "~~~\n$$x$$\n~~~",
    "```\nunclosed fence \\(x\\)\n\n$$y$$",
    "",
])
def test_left_untouched(text):
    out, stats = normalize_math_delimiters(text)
    assert out == text
    assert stats.changed == 0


def test_none_passes_through():
    assert normalize_math_delimiters(None)[0] is None


def test_math_in_a_table_row_stays_on_one_line():
    assert norm(r"| PPO | \(96.2 \pm 5.0\%\) | \[ x \] |") == r"| PPO | $96.2 \pm 5.0\%$ | $x$ |"


def test_unpaired_delimiter_is_left_and_counted():
    out, stats = normalize_math_delimiters("a stray \\[ here, then\n\\[\nx\n\\]")
    assert out == "a stray \\[ here, then\n$$\nx\n$$"
    assert (stats.display, stats.unbalanced) == (1, 1)


def test_inline_parens_do_not_pair_across_paragraphs():
    out, stats = normalize_math_delimiters("open \\(a\n\nclose b\\)")
    assert out == "open \\(a\n\nclose b\\)"
    assert stats.unbalanced == 2


def test_blockquote_prefix_is_carried_onto_each_line():
    assert norm("> note\n> \\[\n> a = b\n> \\]") == "> note\n> $$\n> a = b\n> $$"


QWEN_SAMPLE = r"""### 4. Key High-Level Ideas

Let the observed historical window be
\[
x = [x_1, \dots, x_T] \in \mathbb{R}^{T \times M},
\]
where \(M\) is the number of variables.

- \(k=0\) corresponds to the original forecasting MSE,
- \(k=1\) encourages consistency of trends.

1. **Informal claim.** The paper argues that
   \[
   \Delta^k f_\theta(x) \approx f_\theta(\Delta^k x),
   \]
   but gives only intuition.

### 6. Ratings
<ratings>
  <quality_rating>3.0</quality_rating>
  <quality_justification>Loss \(\mathcal{L}\) is ad hoc.</quality_justification>
  <relevance_rating>2.5</relevance_rating>
  <relevance_justification>Tangential.</relevance_justification>
</ratings>
"""

GEMMA_SAMPLE = r"""The estimator is $\hat{\Sigma}_{RL}$, defined as

$$\hat{\Sigma}_{RL} = \hat{\Sigma}_{LW} + \text{Agent}(\mathcal{S})$$

with commissions of $\$1.50$/contract.
"""


@pytest.mark.parametrize("sample", [QWEN_SAMPLE, GEMMA_SAMPLE])
def test_normalizing_twice_changes_nothing_more(sample):
    once = norm(sample)
    assert once != sample
    assert norm(once) == once


def test_qwen_sample_ends_with_no_backslash_delimiters():
    out, stats = normalize_math_delimiters(QWEN_SAMPLE)
    assert not any(d in out for d in ("\\(", "\\)", "\\[", "\\]"))
    assert (stats.inline, stats.display, stats.unbalanced) == (4, 2, 0)
    assert "<quality_rating>3.0</quality_rating>" in out


def test_report_generation_normalizes_and_logs(capsys):
    out = agent._normalize_report_math(QWEN_SAMPLE)
    assert "\\(" not in out and "$M$" in out
    assert "Math delimiters normalised: 4 inline, 2 display, 0 single-line $$" in capsys.readouterr().out


def test_report_generation_is_silent_when_nothing_changes(capsys):
    text = "Plain report with $x$ only."
    assert agent._normalize_report_math(text) == text
    assert capsys.readouterr().out == ""
