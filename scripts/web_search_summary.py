"""
Summarises the web search log, to judge whether search is worth keeping (decision 0022).

    .venv/bin/python scripts/web_search_summary.py
    .venv/bin/python scripts/web_search_summary.py --since 2026-12-01 --details 5

"Cited" means the finished report used a result's [W1] marker. It shows what the model
used, not whether that use improved the review.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config


def load_entries(path: Path, since: str = None):
    entries, bad = [], 0
    if not path.exists():
        return entries, bad
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if since and entry.get("timestamp", "")[:10] < since:
            continue
        entries.append(entry)
    return entries, bad


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


def summarise(entries) -> str:
    reviews = len(entries)
    status = Counter(e.get("search_status") for e in entries)
    searched = [e for e in entries if e.get("search_status") == "searched"]
    results = [r for e in entries for r in e.get("results", [])]
    cited = [r for r in results if r.get("cited")]
    with_citation = sum(any(r.get("cited") for r in e.get("results", [])) for e in searched)
    credits = sum(e.get("credits", 0) for e in entries)
    queries = [q for e in entries for q in e.get("queries", [])]

    lines = [
        f"Reviews logged:            {reviews}",
        f"Model searched:            {len(searched)} ({pct(len(searched), reviews)})",
        f"Model chose not to:        {status.get('no_search', 0)}",
        f"Search unavailable/failed: {status.get('unavailable', 0) + status.get('failed', 0)}",
        f"Credits used:              {credits}",
        f"Queries sent:              {sum(q.get('status') in ('ok', 'error') for q in queries)}",
        f"Queries rejected:          {sum(q.get('status') == 'rejected' for q in queries)}",
        f"Results returned:          {len(results)}",
        f"Results cited:             {len(cited)} ({pct(len(cited), len(results))})",
        f"Searched reviews citing:   {with_citation} of {len(searched)} ({pct(with_citation, len(searched))})",
        f"Credits per cited result:  {credits / len(cited):.1f}" if cited else "Credits per cited result:  n/a",
    ]

    by_purpose = defaultdict(lambda: [0, 0])
    for entry in entries:
        for result in entry.get("results", []):
            index = result.get("query_index", -1)
            all_queries = entry.get("queries", [])
            purpose = all_queries[index].get("purpose", "unspecified") if 0 <= index < len(all_queries) else "unspecified"
            by_purpose[purpose][0] += 1
            by_purpose[purpose][1] += bool(result.get("cited"))
    if by_purpose:
        lines += ["", "Results cited by purpose:"]
        for purpose, (total, used) in sorted(by_purpose.items()):
            lines.append(f"  {purpose:<12} {used} of {total} ({pct(used, total)})")

    domains = Counter(r.get("domain", "?") for r in cited)
    if domains:
        lines += ["", "Most-cited domains:"]
        lines += [f"  {domain:<32} {count}" for domain, count in domains.most_common(10)]
    return "\n".join(lines)


def details(entries, count: int) -> str:
    blocks = []
    for entry in entries[-count:]:
        block = [f"\n{entry.get('timestamp', '')}  {entry.get('paper_title', '')}",
                 f"  {entry.get('search_status')}: {entry.get('reason') or '-'}"]
        for index, query in enumerate(entry.get("queries", [])):
            note = f" ({query['error']})" if query.get("error") else ""
            block.append(f"  Q: [{query.get('purpose')}] {query.get('query')} -> {query.get('status')}{note}")
            for result in entry.get("results", []):
                if result.get("query_index") == index:
                    mark = f"cited x{result.get('citations')}" if result.get("cited") else "not cited"
                    block.append(f"     {result.get('id')} {mark}: {result.get('title')} <{result.get('url')}>")
        blocks.append("\n".join(block))
    return "\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise the web search log.")
    parser.add_argument("--path", default=config.WEB_SEARCH_LOG_PATH)
    parser.add_argument("--since", help="Only entries from this date, YYYY-MM-DD")
    parser.add_argument("--details", type=int, default=0, help="Also list the last N reviews")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.is_absolute():
        path = ROOT / path
    entries, bad = load_entries(path, args.since)
    if not entries:
        print(f"No web search entries in {path}.")
        return
    print(summarise(entries))
    if args.details:
        print(details(entries, args.details))
    if bad:
        print(f"\n[!] Skipped {bad} unreadable log line(s).")


if __name__ == "__main__":
    main()
