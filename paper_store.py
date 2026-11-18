"""
PDFs the user downloaded for papers the app could not fetch (decision 0020).

The files stay where the user saved them. config.USER_PDF_INDEX maps each paper to its
file's path, so retrieval and the EndNote export can read the PDF:

    {"<key>": {"path": "/Users/.../Downloads/3858063.3858848.pdf", "url": "...",
               "title": "...", "added": "2026-11-18T09:00:00"}}

The key is the lowercase DOI in the paper's URL, so /doi/abs/ and /doi/full/ links to one
paper share it, or a hash of the URL when there is no DOI.
"""
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pymupdf

import academic_api
import config

_lock = threading.Lock()

# Text of the first pages of each PDF already read, by (path, size, mtime_ns), so a
# second scan in the same session does not reparse unchanged files.
_scan_cache: Dict[tuple, str] = {}
SCAN_PAGES = 2


def paper_key(url: str) -> str:
    doi = academic_api.extract_doi_from_url(url or "")
    if doi:
        return doi.lower()
    return "url-" + hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:16]


def _load_index() -> Dict[str, Dict[str, str]]:
    path = Path(config.USER_PDF_INDEX)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[-] Could not read {path}: {e}")
        return {}


def _save_index(index: Dict[str, Dict[str, str]]) -> None:
    path = Path(config.USER_PDF_INDEX)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def pdf_for(url: str) -> Optional[str]:
    """The path of the user's PDF for this paper, if one is recorded and the file still exists."""
    if not url:
        return None
    with _lock:
        entry = _load_index().get(paper_key(url))
    if entry and entry.get("path") and Path(entry["path"]).is_file():
        return entry["path"]
    return None


def register(url: str, path: str, title: Optional[str] = None) -> None:
    with _lock:
        index = _load_index()
        index[paper_key(url)] = {
            "path": str(Path(path).resolve()),
            "url": url,
            "title": title or "",
            "added": datetime.now().isoformat(timespec="seconds"),
        }
        _save_index(index)


def _first_pages_text(path: Path) -> str:
    """Whitespace-free, lowercase text of the PDF's first pages ("" if it cannot be read)."""
    try:
        stat = path.stat()
    except OSError:
        return ""
    cache_key = (str(path), stat.st_size, stat.st_mtime_ns)
    if cache_key in _scan_cache:
        return _scan_cache[cache_key]
    text = ""
    try:
        with pymupdf.open(path) as doc:
            text = "".join(doc[i].get_text("text") for i in range(min(SCAN_PAGES, doc.page_count)))
    except Exception as e:
        print(f"[-] Could not read {path.name}: {e}")
    # A DOI broken over two lines must still match, so all whitespace goes.
    compact = re.sub(r"\s+", "", text).lower()
    _scan_cache[cache_key] = compact
    return compact


def _doi_in(compact_text: str, doi: str) -> bool:
    # The DOI must not run on into more digits: 10.1145/3808131 is not 10.1145/38081312
    # or 10.1145/3808131.3808200.
    return re.search(re.escape(doi) + r"(?![0-9]|\.[0-9])", compact_text) is not None


def recent_pdfs(folder: str, days: float) -> List[Path]:
    """PDFs at the top level of folder, modified in the last `days` days, newest first."""
    root = Path(folder)
    if not root.is_dir():
        return []
    cutoff = time.time() - days * 86400
    found = []
    for entry in root.iterdir():
        try:
            if entry.suffix.lower() == ".pdf" and entry.is_file() and entry.stat().st_mtime >= cutoff:
                found.append(entry)
        except OSError:
            continue
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def match_pdfs(pdf_paths: Iterable[Path], dois: Iterable[str]) -> Dict[str, Path]:
    """
    Matches PDFs to papers by the DOI printed in their first pages.
    Returns {doi: path}. A PDF naming more than one of the DOIs is ambiguous and ignored;
    when two PDFs name the same DOI, the first one (the newest from recent_pdfs) wins.
    """
    wanted = sorted({d.lower() for d in dois if d})
    matches: Dict[str, Path] = {}
    if not wanted:
        return matches
    for path in pdf_paths:
        compact = _first_pages_text(path)
        if not compact:
            continue
        hits = [doi for doi in wanted if _doi_in(compact, doi)]
        if len(hits) == 1 and hits[0] not in matches:
            matches[hits[0]] = path
        elif len(hits) > 1:
            print(f"[*] {path.name} names {len(hits)} failed papers' DOIs; not attached to any.")
    return matches
