r"""
Rewrite LaTeX math delimiters in LLM markdown into the one form the frontend renders.

The frontend parses math with remark-math, which only knows `$...$` and `$$...$$`.
Some models (qwen3.8) write `\(...\)` and `\[...\]` instead; markdown reads those as
escaped brackets, so the equations show up as plain text. Others (gemma-4) write display
equations as `$$x$$` on a single line, which remark-math treats as inline math.

Canonical form produced here:
  inline   $x$
  display  $$        <- alone on its line
           x
           $$        <- alone on its line

Left untouched: fenced code, inline code, display blocks already in canonical form,
`$$x$$` in the middle of a sentence, LaTeX's `\\[2pt]` row spacing, and escaped
citation-style brackets such as `\[12\]`. A delimiter with no partner is left as it is
and counted in `unbalanced`.
"""

import re
import textwrap
from dataclasses import dataclass

# Quote markers and a list marker that may precede content on a line.
_LEAD = r"[ \t]*(?:>[ \t]?)*"
_MARKER = r"(?:[-*+]|\d+[.)])[ \t]+"
_LINE_HEAD = re.compile(rf"(?P<lead>{_LEAD})(?P<marker>{_MARKER})?")

_NOT_BLANK_LINE = r"(?!\n[ \t]*\n)"
_OPEN_BRACKET = r"(?<!\\)\\\["
_CLOSE_BRACKET = r"(?<!\\)\\\]"

_TOKEN = re.compile(
    rf"""
    # Fenced code block; an unclosed fence runs to the end of the document.
    (?P<fence>^{_LEAD}(?:{_MARKER})?(?P<fmark>`{{3,}}|~{{3,}})[^\n]*
        (?:\n.*?)??(?:\n[ \t>]*(?P=fmark)[`~]*[ \t]*(?=\n|\Z)|\Z))
    # Inline code span.
  | (?P<code>(?<!`)(?P<tick>`+)(?!`)(?:{_NOT_BLANK_LINE}.)+?(?<!`)(?P=tick)(?!`))
    # $$ ... $$
  | (?P<dollars>\$\$(?P<dbody>(?:(?!\$\$).)+?)\$\$)
    # \[ ... \] with no other \[ inside, so a stray opener cannot swallow a later block.
  | (?P<bracket>{_OPEN_BRACKET}(?P<bbody>(?:(?!{_OPEN_BRACKET}).)*?){_CLOSE_BRACKET})
    # \( ... \) within one paragraph.
  | (?P<paren>(?<!\\)\\\((?P<pbody>(?:{_NOT_BLANK_LINE}.)+?)(?<!\\)\\\))
    """,
    re.VERBOSE | re.MULTILINE | re.DOTALL,
)

_QUOTE_PREFIX = re.compile(r"^[ \t]*(?:>[ \t]?)+", re.MULTILINE)
_KINDS = ("fence", "code", "dollars", "bracket", "paren")
_STRAY = re.compile(r"(?<!\\)\\[\[\]()]")
_CITATION = re.compile(r"[\d\s,;–-]+")
_TRAILING_PUNCT = re.compile(r"[ \t]*([.,;:])[ \t]*")


@dataclass
class MathStats:
    inline: int = 0      # \(x\)  -> $x$
    display: int = 0     # \[x\]  -> fenced $$
    promoted: int = 0    # $$x$$ on one line -> fenced $$
    unbalanced: int = 0  # \( \) \[ \] left without a partner

    @property
    def changed(self):
        return self.inline + self.display + self.promoted

    def summary(self):
        return f"{self.inline} inline, {self.display} display, {self.promoted} single-line $$"


def _line_bounds(text, start, end):
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return line_start, len(text) if line_end == -1 else line_end


def _continuation(prefix):
    """Indentation that keeps a following line inside the same list item or quote."""
    head = _LINE_HEAD.match(prefix)
    return head.group("lead") + " " * len(head.group("marker") or ""), head.end()


def _fenced(body, cont):
    if ">" in cont:
        # Inside a quote the body lines carry their own "> " markers; cont re-adds them.
        body = _QUOTE_PREFIX.sub("", body)
    lines = textwrap.dedent(body.strip("\n")).strip().split("\n")
    blank = cont.rstrip()
    body_lines = [cont + line if line.strip() else blank for line in lines]
    return "\n".join(["$$", *body_lines, cont + "$$"])


def normalize_math_delimiters(text):
    """Return (text with canonical math delimiters, MathStats)."""
    stats = MathStats()
    if not text:
        return text, stats

    out = []
    pos = 0

    def gap(upto):
        chunk = text[pos:upto]
        stats.unbalanced += len(_STRAY.findall(chunk))
        out.append(chunk)

    for m in _TOKEN.finditer(text):
        if m.start() < pos:
            continue
        kind = next(k for k in _KINDS if m.group(k) is not None)

        if kind in ("fence", "code"):
            gap(m.start())
            out.append(m.group(0))
            pos = m.end()
            continue

        if kind == "paren":
            body = " ".join(m.group("pbody").split())
            gap(m.start())
            if body:
                out.append(f"${body}$")
                stats.inline += 1
            else:
                out.append(m.group(0))
            pos = m.end()
            continue

        body = m.group("dbody") if kind == "dollars" else m.group("bbody")
        line_start, line_end = _line_bounds(text, m.start(), m.end())
        prefix = text[line_start:m.start()]
        rest = text[m.end():line_end]
        cont, head_end = _continuation(prefix)
        prefix_has_text = bool(prefix[head_end:].strip())
        punct = _TRAILING_PUNCT.fullmatch(rest)
        rest_is_text = bool(rest.strip()) and not punct

        if kind == "dollars":
            canonical = (
                not prefix_has_text and not rest.strip()
                and re.match(r"[ \t]*\n", body) and re.search(r"\n[ \t>]*\Z", body)
            )
            # Mid-sentence $$x$$ is ambiguous (inline or display?), so it stays as written.
            if canonical or prefix_has_text or rest_is_text or not body.strip():
                gap(m.start())
                out.append(m.group(0))
                pos = m.end()
                continue
        else:
            single_line = "\n" not in body
            if not body.strip() or (single_line and _CITATION.fullmatch(body)):
                gap(m.start())
                out.append(m.group(0))
                pos = m.end()
                continue
            if prefix.lstrip().startswith("|"):
                # A table row cannot hold a multi-line block.
                gap(m.start())
                out.append(f"${' '.join(body.split())}$")
                stats.display += 1
                pos = m.end()
                continue

        gap(m.start())
        if prefix_has_text:
            # Break the equation out of the sentence it was written in.
            out[-1] = out[-1].rstrip(" \t")
            out.append("\n" + cont)
        if punct:
            body = body.rstrip() + punct.group(1)
        out.append(_fenced(body, cont))
        if rest_is_text:
            out.append("\n" + cont)
            pos = m.end() + (len(rest) - len(rest.lstrip(" \t")))
        else:
            pos = line_end
        if kind == "dollars":
            stats.promoted += 1
        else:
            stats.display += 1

    gap(len(text))
    return "".join(out), stats
