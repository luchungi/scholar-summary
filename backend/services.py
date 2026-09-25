import os
import sys
import queue
import io
import difflib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from sqlmodel import Session, select
from backend.models import Run, Paper, EmailAlert
from backend.database import engine
import re

def extract_ratings(content: str):
    quality_rating = None
    relevance_rating = None

    # Try XML tags extraction first
    q_match = re.search(r'<quality_rating>\s*([0-9.]+)\s*</quality_rating>', content, re.DOTALL | re.IGNORECASE)
    if q_match:
        try:
            quality_rating = float(q_match.group(1))
        except ValueError:
            pass

    r_match = re.search(r'<relevance_rating>\s*([0-9.]+)\s*</relevance_rating>', content, re.DOTALL | re.IGNORECASE)
    if r_match:
        try:
            relevance_rating = float(r_match.group(1))
        except ValueError:
            pass

    if quality_rating is not None and relevance_rating is not None:
        return quality_rating, relevance_rating

    sections = re.split(r'^(?=#{1,4}\s+)', content, flags=re.MULTILINE)

    for sec in sections:
        lines = sec.splitlines()
        first_line = lines[0] if lines else ''
        if quality_rating is None and re.search(r'quality\s+rating', first_line, re.IGNORECASE):
            match_in_header = re.search(r'(?:rating:?\s*)?\*?\*?\s*([0-9.]+)\s*/\s*5', first_line, re.IGNORECASE)
            if match_in_header:
                quality_rating = float(match_in_header.group(1))
            else:
                match_in_body = re.search(r'\*\*Rating:\s*([0-9.]+)\s*/\s*5', sec, re.IGNORECASE)
                if not match_in_body:
                    match_in_body = re.search(r'rating:\s*([0-9.]+)\s*/\s*5', sec, re.IGNORECASE)
                if match_in_body:
                    quality_rating = float(match_in_body.group(1))

        elif relevance_rating is None and re.search(r'relevance\s+(?:to\s+)?user\s+interests|relevance\s+rating', first_line, re.IGNORECASE):
            match_in_header = re.search(r'(?:rating:?\s*)?\*?\*?\s*([0-9.]+)\s*/\s*5', first_line, re.IGNORECASE)
            if match_in_header:
                relevance_rating = float(match_in_header.group(1))
            else:
                match_in_body = re.search(r'\*\*Relevance Rating:\s*([0-9.]+)\s*/\s*5', sec, re.IGNORECASE)
                if not match_in_body:
                    match_in_body = re.search(r'\*\*Rating:\s*([0-9.]+)\s*/\s*5', sec, re.IGNORECASE)
                if not match_in_body:
                    match_in_body = re.search(r'relevance rating:\s*([0-9.]+)\s*/\s*5', sec, re.IGNORECASE)
                if not match_in_body:
                    match_in_body = re.search(r'rating:\s*([0-9.]+)\s*/\s*5', sec, re.IGNORECASE)
                if match_in_body:
                    relevance_rating = float(match_in_body.group(1))

    # Global fallback if not found in sections
    if quality_rating is None:
        match = re.search(r'\*?\*?rating\*?\*?:?\*?\*?\s*([0-9.]+)\s*/\s*5', content, re.IGNORECASE)
        if match:
            quality_rating = float(match.group(1))

    if relevance_rating is None:
        match = re.search(r'relevance\*?\*?:?\*?\*?\s*([0-9.]+)\s*/\s*5', content, re.IGNORECASE)
        if match:
            relevance_rating = float(match.group(1))
        else:
            all_ratings = re.findall(r'\*?\*?rating\*?\*?:?\*?\*?\s*([0-9.]+)\s*/\s*5', content, re.IGNORECASE)
            if len(all_ratings) >= 2:
                relevance_rating = float(all_ratings[1])

    return quality_rating, relevance_rating

# Import original components from root folder
sys.path.append(str(Path(__file__).resolve().parents[1]))
import config
import gmail_fetcher
import paper_retriever
import agent
from main import (
    ensure_interests_file,
    sanitize_filename,
    print_diff,
    normalize_url,
    remove_duplicate_links
)

# In-memory dictionary to hold live log queues for running jobs
active_logs: Dict[int, queue.Queue] = {}

class _ThreadLogRouter(io.TextIOBase):
    """
    Routes writes to per-thread queues. Threads that haven't registered a queue
    fall through to the original stream, so concurrent runs can never
    cross-contaminate each other's log streams.
    """
    def __init__(self, fallback):
        self.fallback = fallback
        self.routes: Dict[int, queue.Queue] = {}
    def register(self, q: queue.Queue):
        self.routes[threading.get_ident()] = q
    def unregister(self):
        self.routes.pop(threading.get_ident(), None)
    def write(self, s):
        q = self.routes.get(threading.get_ident())
        if q is not None:
            if s:
                q.put(s)
            return len(s)
        return self.fallback.write(s)
    def flush(self):
        if threading.get_ident() not in self.routes:
            self.fallback.flush()

# Install the routers once at import time
_stdout_router = _ThreadLogRouter(sys.stdout)
_stderr_router = _ThreadLogRouter(sys.stderr)
sys.stdout = _stdout_router
sys.stderr = _stderr_router

class LogCapture:
    """
    Context manager routing the current thread's stdout/stderr to a queue.
    """
    def __init__(self, q: queue.Queue):
        self.q = q
    def __enter__(self):
        _stdout_router.register(self.q)
        _stderr_router.register(self.q)
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        _stdout_router.unregister()
        _stderr_router.unregister()

# Single-active-run guard: LM Studio serves one model, so overlapping runs only
# contend for it. POST /api/runs returns the active run instead of starting another.
_run_state_lock = threading.Lock()
_active_run_id: Optional[int] = None

def get_active_run() -> Optional[Run]:
    with _run_state_lock:
        rid = _active_run_id
    if rid is None:
        return None
    with Session(engine) as session:
        run = session.get(Run, rid)
    if run and run.status == "running":
        return run
    return None

def _set_active_run(run_id: int):
    global _active_run_id
    with _run_state_lock:
        _active_run_id = run_id

def _clear_active_run(run_id: int):
    global _active_run_id
    with _run_state_lock:
        if _active_run_id == run_id:
            _active_run_id = None

def _extract_canonical_id(url: str) -> Optional[str]:
    """
    Extracts a canonical paper identifier from a URL so the same paper is
    recognized across different links (abs vs pdf, v1 vs v2, doi resolver, etc.).
    """
    m = re.search(r'arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?', url, re.IGNORECASE)
    if m:
        return f"arxiv:{m.group(1)}"
    m = re.search(r'doi\.org/(10\.\d{4,9}/[^\s?#]+)', url, re.IGNORECASE)
    if m:
        return f"doi:{m.group(1).lower()}"
    m = re.search(r'ssrn\.com/.*abstract(?:_id)?=(\d+)', url, re.IGNORECASE)
    if m:
        return f"ssrn:{m.group(1)}"
    return None

def _normalize_title(title: str) -> str:
    """
    Lowercases and strips everything but alphanumerics, so spacing glitches and
    glued words from Scholar alerts ('forportfolioestimation') compare equal.
    """
    return re.sub(r'[^a-z0-9]', '', (title or "").lower())

TITLE_MATCH_RATIO = 0.90
MIN_TITLE_MATCH_LEN = 20  # don't fuzzy-match very short/generic titles

def annotate_links_with_history(alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Marks alert links that correspond to papers already in the DB.
    Layered matching: exact normalized URL -> canonical ID (arXiv/DOI/SSRN) ->
    fuzzy normalized-title similarity. Adds previous_status, match_type, and
    matched_title to each matched link.
    """
    with Session(engine) as session:
        papers = session.exec(select(Paper)).all()

    # Prefer successful papers when several records exist for the same key
    papers.sort(key=lambda p: 0 if p.status == "success" else 1)

    by_url: Dict[str, Paper] = {}
    by_id: Dict[str, Paper] = {}
    title_index: List[tuple] = []
    for p in papers:
        if p.url and p.url not in by_url:
            by_url[p.url] = p
        cid = _extract_canonical_id(p.url or "")
        if cid and cid not in by_id:
            by_id[cid] = p
        norm = _normalize_title(p.title)
        if len(norm) >= MIN_TITLE_MATCH_LEN:
            title_index.append((norm, p))

    for alert in alerts:
        for link in alert.get("links", []):
            url = (link.get("url") or "").strip()
            title = link.get("title") or ""

            match, match_type = by_url.get(url), "url"
            if not match:
                cid = _extract_canonical_id(url)
                match, match_type = (by_id.get(cid), "id") if cid else (None, None)
            if not match:
                norm = _normalize_title(title)
                if len(norm) >= MIN_TITLE_MATCH_LEN:
                    best, best_ratio = None, 0.0
                    for norm_title, p in title_index:
                        ratio = difflib.SequenceMatcher(None, norm, norm_title).ratio()
                        if ratio > best_ratio:
                            best_ratio, best = ratio, p
                    if best_ratio >= TITLE_MATCH_RATIO:
                        match, match_type = best, "title"

            if match:
                link["previous_status"] = match.status
                link["match_type"] = match_type
                link["matched_title"] = match.title

    return alerts

def get_latest_alerts_from_gmail() -> List[Dict[str, Any]]:
    """
    Fetches Gmail Google Alerts, syncs new ones to the DB, and returns alert structures.
    """
    config.validate_config()
    raw_alerts = gmail_fetcher.fetch_latest_alerts(
        credentials_path=config.GMAIL_CREDENTIALS_PATH,
        token_path=config.GMAIL_TOKEN_PATH,
        limit=config.MAX_EMAIL_FETCH
    )

    # Normalize URLs and deduplicate links across emails
    raw_alerts = remove_duplicate_links(raw_alerts)

    # Mark links that match papers already analyzed/failed/skipped in the DB
    raw_alerts = annotate_links_with_history(raw_alerts)

    new_alerts = []
    with Session(engine) as session:
        for alert in raw_alerts:
            # Check if this email alert was already fetched
            stmt = select(EmailAlert).where(EmailAlert.message_id == alert["id"])
            existing = session.exec(stmt).first()
            if not existing:
                db_alert = EmailAlert(
                    message_id=alert["id"],
                    subject=alert["subject"],
                    date=alert["date"],
                    processed=False
                )
                session.add(db_alert)
                new_alerts.append(alert)
        session.commit()

    return raw_alerts

def extract_web_page_title(url: str) -> Optional[str]:
    """
    Attempts to fetch the target URL and parse its HTML <title> tag.
    Special parsing is added for arXiv PDFs to extract the title from the abstract page.
    """
    try:
        resolved = paper_retriever.resolve_url(url)
        parsed = urlparse(resolved)

        # Special case for arXiv PDF: convert /pdf/... to /abs/... to parse the title
        if "arxiv.org" in parsed.netloc and "/pdf/" in parsed.path:
            abs_path = parsed.path.replace("/pdf/", "/abs/")
            # Strip trailing .pdf if present
            if abs_path.endswith(".pdf"):
                abs_path = abs_path[:-4]
            abs_url = f"https://arxiv.org{abs_path}"

            res = requests.get(abs_url, headers=paper_retriever.HEADERS, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                title_el = soup.find("h1", class_="title")
                if title_el:
                    # Remove "Title:" prefix
                    return title_el.text.replace("Title:", "").strip()

        # General case
        res = requests.get(resolved, headers=paper_retriever.HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            if soup.title and soup.title.string:
                return soup.title.string.strip()
    except Exception as e:
        print(f"[-] Error auto-extracting web page title: {e}")
    return None

def run_paper_processing_task(
    run_id: int,
    papers_to_process: List[Dict[str, str]],
    q: queue.Queue
):
    """
    Synchronous task runner that compiles summaries, updates the SQLite tables,
    and captures stdout to the queue.
    """
    with LogCapture(q):
        print(f"[+] Starting paper processing run {run_id} at {datetime.now()}")
        print(f"[+] Papers to process: {len(papers_to_process)}")

        success_count = 0
        failure_count = 0
        skipped_count = 0

        # Load user interests
        try:
            current_interests = ensure_interests_file()
        except Exception as e:
            print(f"[-] Error loading user interests: {e}")
            current_interests = ""

        for idx, paper_info in enumerate(papers_to_process, 1):
            title = paper_info.get("title", "").strip()
            url = paper_info.get("url")
            force = str(paper_info.get("force", "")).lower() in ("true", "1", "yes")

            print("\n" + "=" * 60)
            print(f"[{idx}/{len(papers_to_process)}] Fetching paper text for URL: {url}")
            print("=" * 60)

            # Fetch text
            paper_text = None
            retrieval = None
            try:
                retrieval = paper_retriever.retrieve_paper(url)
                paper_text = retrieval["text"] if retrieval else None
            except Exception as e:
                print(f"[-] Error retrieving paper: {e}")

            if not paper_text:
                print("[-] Skipping paper: could not retrieve text.")
                failure_count += 1
                with Session(engine) as session:
                    db_title = title
                    if not db_title or db_title in ("Manual URL Analysis", "Manual Input Paper", "Untitled"):
                        db_title = extract_web_page_title(url) or "Manual Input Paper"

                    # Check if this paper URL is already listed as failed (match by URL only)
                    stmt = select(Paper).where(
                        Paper.url == url,
                        Paper.status == "failed"
                    )
                    existing_failed = session.exec(stmt).first()
                    if not existing_failed:
                        db_paper = Paper(
                            title=db_title,
                            url=url,
                            status="failed",
                            run_id=run_id
                        )
                        session.add(db_paper)
                    else:
                        existing_failed.title = db_title  # Update title if refined
                        existing_failed.date_processed = datetime.now(timezone.utc).replace(tzinfo=None)
                        existing_failed.run_id = run_id
                        session.add(existing_failed)
                    session.commit()
                continue

            # If the title is generic, auto-extract the paper title
            if not title or title in ("Manual URL Analysis", "Manual Input Paper", "Untitled"):
                print(f"[*] Title is generic. Extracting title from paper text using LLM...")
                extracted_title = agent.extract_paper_title(paper_text)
                if extracted_title:
                    title = extracted_title
                    print(f"[+] Extracted clean title from paper text: {title}")
                else:
                    print(f"[*] Fallback: extracting title from web page metadata...")
                    extracted_title = extract_web_page_title(url)
                    if extracted_title:
                        title = extracted_title
                        print(f"[+] Extracted clean title from metadata: {title}")
                    else:
                        title = "Manual Input Paper"

            print(f"[+] Processing paper: {title}")
            print(f"[+] Retrieved {len(paper_text)} characters of text.")

            # Relevance pre-filter gate: skip full analysis for off-profile papers
            if config.RELEVANCE_GATE_ENABLED and not force:
                gate_score, gate_reason = agent.assess_relevance(title, paper_text[:3000], current_interests)
                if gate_score is not None and gate_score < config.RELEVANCE_GATE_THRESHOLD:
                    print(f"[*] Skipping paper: relevance pre-check scored {gate_score}/5 "
                          f"(threshold {config.RELEVANCE_GATE_THRESHOLD}). Reason: {gate_reason}")
                    skipped_count += 1
                    with Session(engine) as session:
                        stmt = select(Paper).where(
                            Paper.url == url,
                            Paper.status == "skipped"
                        )
                        existing_skipped = session.exec(stmt).first()
                        if not existing_skipped:
                            existing_skipped = Paper(title=title, url=url, status="skipped", run_id=run_id)
                        existing_skipped.title = title
                        existing_skipped.relevance_rating = gate_score
                        existing_skipped.skip_reason = gate_reason
                        existing_skipped.date_processed = datetime.now(timezone.utc).replace(tzinfo=None)
                        existing_skipped.run_id = run_id
                        session.add(existing_skipped)
                        session.commit()
                    continue
                elif gate_score is not None:
                    print(f"[+] Relevance pre-check passed: {gate_score}/5. Proceeding to full analysis.")

            # Factual access note computed by the retriever (the LLM is told not to speculate)
            if retrieval:
                source_label = ("PDF (downloaded and parsed)" if retrieval["source"] == "pdf"
                                else "HTML scrape of the landing page (full PDF may not have been accessible)")
                access_info = f"Text obtained via {source_label}; {retrieval['raw_chars']} characters extracted"
                access_info += "; middle of the paper truncated to fit the context budget." if retrieval["truncated"] else "."
            else:
                access_info = None

            # Generate summary report using LM Studio LLM
            try:
                report = agent.generate_paper_report(title, url, paper_text, current_interests, access_info)
                header = f"# {title}\n\n**Link**: [{url}]({url})\n\n"
                if access_info:
                    header += f"**Source**: {access_info}\n\n"
                report = header + "---\n\n" + report

                # Save markdown file
                os.makedirs(config.REPORTS_DIR, exist_ok=True)
                safe_title = sanitize_filename(title)
                report_path = Path(config.REPORTS_DIR) / f"report_{safe_title}.md"
                report_path.write_text(report, encoding="utf-8")

                print(f"[+] Report saved to {report_path}")
                success_count += 1

                # Save to database
                q_val, r_val = extract_ratings(report)
                with Session(engine) as session:
                    db_paper = Paper(
                        title=title,
                        url=url,
                        status="success",
                        report_path=str(report_path),
                        run_id=run_id,
                        quality_rating=q_val,
                        relevance_rating=r_val
                    )
                    session.add(db_paper)

                    # Delete any previous failed/skipped records for this URL
                    stmt = select(Paper).where(
                        Paper.url == url,
                        Paper.status.in_(["failed", "skipped"])
                    )
                    for existing in session.exec(stmt).all():
                        session.delete(existing)

                    session.commit()

            except Exception as e:
                print(f"[-] Error generating report: {e}")
                failure_count += 1
                with Session(engine) as session:
                    # Match by URL only
                    stmt = select(Paper).where(
                        Paper.url == url,
                        Paper.status == "failed"
                    )
                    existing_failed = session.exec(stmt).first()
                    if not existing_failed:
                        db_paper = Paper(
                            title=title,
                            url=url,
                            status="failed",
                            run_id=run_id
                        )
                        session.add(db_paper)
                    else:
                        existing_failed.title = title
                        existing_failed.date_processed = datetime.now(timezone.utc).replace(tzinfo=None)
                        existing_failed.run_id = run_id
                        session.add(existing_failed)
                    session.commit()

        # Complete run updates
        print(f"\n[+] Run {run_id} finished! Succeeded: {success_count}, "
              f"Failed: {failure_count}, Skipped (low relevance): {skipped_count}")
        with Session(engine) as session:
            db_run = session.get(Run, run_id)
            if db_run:
                db_run.status = "completed" if failure_count == 0 else "failed"
                db_run.papers_processed = success_count
                db_run.papers_failed = failure_count
                session.add(db_run)
                session.commit()

    _clear_active_run(run_id)
    # Signal the end of logging
    q.put(None)

def start_paper_run(papers_to_process: List[Dict[str, str]], emails_fetched: int = 0) -> Run:
    """
    Creates a Run entry in the DB, launches the thread runner, and initializes the log queue.
    If a run is already in progress, returns that run instead of starting another.
    """
    existing = get_active_run()
    if existing:
        print(f"[*] Run {existing.id} is already in progress; not starting a new run.")
        return existing

    with Session(engine) as session:
        db_run = Run(
            status="running",
            emails_fetched=emails_fetched
        )
        session.add(db_run)
        session.commit()
        session.refresh(db_run)

        run_id = db_run.id

    q = queue.Queue()
    active_logs[run_id] = q
    _set_active_run(run_id)

    t = threading.Thread(
        target=run_paper_processing_task,
        args=(run_id, papers_to_process, q)
    )
    t.start()

    return db_run

def run_uploaded_paper_task(
    run_id: int,
    file_path: str,
    original_filename: str,
    q: queue.Queue
):
    """
    Synchronous task runner that processes an uploaded PDF in a background thread,
    capturing stdout to the SSE queue.
    """
    with LogCapture(q):
        print(f"[+] Starting manual PDF upload processing run {run_id} at {datetime.now()}")
        print(f"[+] File: {original_filename}")
        
        # 1. Read file bytes
        try:
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()
        except Exception as e:
            print(f"[-] Failed to read uploaded file: {e}")
            with Session(engine) as session:
                db_run = session.get(Run, run_id)
                if db_run:
                    db_run.status = "failed"
                    db_run.papers_failed = 1
                    session.add(db_run)
                    session.commit()
            if os.path.exists(file_path):
                os.remove(file_path)
            _clear_active_run(run_id)
            q.put(None)
            return

        # 2. Extract text
        print("[+] Extracting text from PDF...")
        text = paper_retriever.extract_text_from_pdf(pdf_bytes)
        if not text.strip():
            print("[-] Failed to extract any text from the PDF.")
            with Session(engine) as session:
                db_run = session.get(Run, run_id)
                if db_run:
                    db_run.status = "failed"
                    db_run.papers_failed = 1
                    session.add(db_run)
                    session.commit()
            if os.path.exists(file_path):
                os.remove(file_path)
            _clear_active_run(run_id)
            q.put(None)
            return

        raw_chars = len(text)
        text, was_truncated = paper_retriever.prepare_paper_text(text)
        access_info = f"Text extracted from a user-uploaded PDF; {raw_chars} characters extracted"
        access_info += "; middle of the paper truncated to fit the context budget." if was_truncated else "."

        # 3. Extract title
        print("[+] Extracting paper title using LLM...")
        title = agent.extract_paper_title(text)
        if not title:
            title = Path(original_filename).stem.replace("_", " ").replace("-", " ").title()
        print(f"[+] Paper Title: {title}")

        # 4. Generate report
        try:
            current_interests = ensure_interests_file()
            print(f"[+] Generating summary report using model: {config.LM_STUDIO_MODEL}...")
            report = agent.generate_paper_report(title, "Uploaded File", text, current_interests, access_info)
            report = f"# {title}\n\n**Source**: Uploaded PDF ({original_filename})\n\n**Extraction**: {access_info}\n\n---\n\n" + report

            # Save report file
            os.makedirs(config.REPORTS_DIR, exist_ok=True)
            safe_title = sanitize_filename(title)
            report_path = Path(config.REPORTS_DIR) / f"report_{safe_title}.md"
            report_path.write_text(report, encoding="utf-8")
            print(f"[+] Report saved to {report_path}")

            # Extract ratings
            q_val, r_val = extract_ratings(report)

            # Save Paper to database
            with Session(engine) as session:
                db_paper = Paper(
                    title=title,
                    url=f"file://{original_filename}",
                    status="success",
                    report_path=str(report_path),
                    run_id=run_id,
                    quality_rating=q_val,
                    relevance_rating=r_val
                )
                session.add(db_paper)
                session.commit()

            # Update DB run to completed
            with Session(engine) as session:
                db_run = session.get(Run, run_id)
                if db_run:
                    db_run.status = "completed"
                    db_run.papers_processed = 1
                    session.add(db_run)
                    session.commit()

        except Exception as e:
            print(f"[-] Error generating report: {e}")
            with Session(engine) as session:
                db_paper = Paper(
                    title=title,
                    url=f"file://{original_filename}",
                    status="failed",
                    run_id=run_id
                )
                session.add(db_paper)
                
                db_run = session.get(Run, run_id)
                if db_run:
                    db_run.status = "failed"
                    db_run.papers_failed = 1
                    session.add(db_run)
                session.commit()

        finally:
            # Clean up temp file
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print("[+] Cleaned up temporary upload file.")
                except Exception as clean_err:
                    print(f"[-] Error removing temp file: {clean_err}")

    _clear_active_run(run_id)
    # Signal end of queue
    q.put(None)

def start_uploaded_paper_run(file_path: str, original_filename: str) -> Run:
    """
    Creates a Run entry in the DB, launches the thread runner for the uploaded file,
    and initializes the log queue.
    """
    existing = get_active_run()
    if existing:
        # Unlike Gmail runs, silently attaching to another run would drop the uploaded file
        if os.path.exists(file_path):
            os.remove(file_path)
        raise RuntimeError(
            f"Run {existing.id} is already in progress. Wait for it to finish before uploading."
        )

    with Session(engine) as session:
        db_run = Run(
            status="running",
            emails_fetched=0
        )
        session.add(db_run)
        session.commit()
        session.refresh(db_run)
        run_id = db_run.id

    q = queue.Queue()
    active_logs[run_id] = q
    _set_active_run(run_id)

    t = threading.Thread(
        target=run_uploaded_paper_task,
        args=(run_id, file_path, original_filename, q)
    )
    t.start()

    return db_run

