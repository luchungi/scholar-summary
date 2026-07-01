import os
import sys
import queue
import io
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

class QueueWriter(io.TextIOBase):
    """
    A helper file-like object that redirects write operations to a thread-safe Queue.
    """
    def __init__(self, q: queue.Queue):
        self.q = q
    def write(self, s):
        if s:
            self.q.put(s)
        return len(s)
    def flush(self):
        pass

class LogCapture:
    """
    Context manager to redirect stdout and stderr to a queue.
    """
    def __init__(self, q: queue.Queue):
        self.q = q
        self.old_stdout = sys.stdout
        self.old_stderr = sys.stderr
        self.writer = QueueWriter(q)
    def __enter__(self):
        sys.stdout = self.writer
        sys.stderr = self.writer
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.old_stdout
        sys.stderr = self.old_stderr

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

        # Load user interests
        try:
            current_interests = ensure_interests_file()
        except Exception as e:
            print(f"[-] Error loading user interests: {e}")
            current_interests = ""

        for idx, paper_info in enumerate(papers_to_process, 1):
            title = paper_info.get("title", "").strip()
            url = paper_info.get("url")

            print("\n" + "=" * 60)
            print(f"[{idx}/{len(papers_to_process)}] Fetching paper text for URL: {url}")
            print("=" * 60)

            # Fetch text
            paper_text = None
            try:
                paper_text = paper_retriever.retrieve_paper_text(url)
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

            # Generate summary report using LM Studio LLM
            try:
                report = agent.generate_paper_report(title, url, paper_text, current_interests)
                report = f"# {title}\n\n**Link**: [{url}]({url})\n\n---\n\n" + report

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

                    # Delete any previous failed records for this URL
                    stmt = select(Paper).where(
                        Paper.url == url,
                        Paper.status == "failed"
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
        print(f"\n[+] Run {run_id} finished! Succeeded: {success_count}, Failed: {failure_count}")
        with Session(engine) as session:
            db_run = session.get(Run, run_id)
            if db_run:
                db_run.status = "completed" if failure_count == 0 else "failed"
                db_run.papers_processed = success_count
                db_run.papers_failed = failure_count
                session.add(db_run)
                session.commit()

    # Signal the end of logging
    q.put(None)

def start_paper_run(papers_to_process: List[Dict[str, str]], emails_fetched: int = 0) -> Run:
    """
    Creates a Run entry in the DB, launches the thread runner, and initializes the log queue.
    """
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
            q.put(None)
            return

        # 3. Extract title
        print("[+] Extracting paper title using LLM...")
        title = agent.extract_paper_title(text)
        if not title:
            title = Path(original_filename).stem.replace("_", " ").replace("-", " ").title()
        print(f"[+] Paper Title: {title}")

        # 4. Generate report
        try:
            current_interests = ensure_interests_file()
            print(f"[+] Generating summary report using model: {agent.get_effective_model()}...")
            report = agent.generate_paper_report(title, "Uploaded File", text, current_interests)
            report = f"# {title}\n\n**Source**: Uploaded PDF ({original_filename})\n\n---\n\n" + report

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

        # Signal end of queue
        q.put(None)

def start_uploaded_paper_run(file_path: str, original_filename: str) -> Run:
    """
    Creates a Run entry in the DB, launches the thread runner for the uploaded file,
    and initializes the log queue.
    """
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

    t = threading.Thread(
        target=run_uploaded_paper_task,
        args=(run_id, file_path, original_filename, q)
    )
    t.start()

    return db_run

