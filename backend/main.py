import os
import sys
import queue
import difflib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select

# Root import setup
sys.path.append(str(Path(__file__).resolve().parents[1]))
import config
from backend.database import create_db_and_tables, get_session, engine
from backend.models import Run, Paper, EmailAlert
from backend.services import (
    get_latest_alerts_from_gmail,
    start_paper_run,
    active_logs,
    get_active_run
)
from backend.framework_manager import FrameworkManager
import agent
import model_settings
import paper_retriever
from agent import update_user_interests
from main import ensure_interests_file, sanitize_filename

# Create FastAPI app
app = FastAPI(title="Scholar Summary Agent Web API")

# Add CORS Middleware to support hot-reloading frontend development on port 5173
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def ensure_paper_rating_columns():
    from sqlalchemy import text
    with engine.begin() as conn:
        cursor = conn.execute(text("PRAGMA table_info(paper)"))
        columns = [row[1] for row in cursor.fetchall()]
        
        if "quality_rating" not in columns:
            print("[*] Migrating: Adding quality_rating column to paper table...")
            conn.execute(text("ALTER TABLE paper ADD COLUMN quality_rating FLOAT"))
        if "relevance_rating" not in columns:
            print("[*] Migrating: Adding relevance_rating column to paper table...")
            conn.execute(text("ALTER TABLE paper ADD COLUMN relevance_rating FLOAT"))
        if "skip_reason" not in columns:
            print("[*] Migrating: Adding skip_reason column to paper table...")
            conn.execute(text("ALTER TABLE paper ADD COLUMN skip_reason TEXT"))

def sync_existing_paper_ratings():
    import os
    from sqlmodel import Session, select
    from backend.models import Paper
    from backend.services import extract_ratings
    
    with Session(engine) as session:
        stmt = select(Paper).where(Paper.status == "success", (Paper.quality_rating == None) | (Paper.relevance_rating == None))
        papers = session.exec(stmt).all()
        if not papers:
            return
            
        print(f"[*] Found {len(papers)} papers requiring rating synchronization...")
        for paper in papers:
            if paper.report_path and os.path.exists(paper.report_path):
                try:
                    content = Path(paper.report_path).read_text(encoding="utf-8")
                    q, r = extract_ratings(content)
                    paper.quality_rating = q
                    paper.relevance_rating = r
                    session.add(paper)
                    print(f"[+] Synced ratings for '{paper.title}': Quality={q}, Relevance={r}")
                except Exception as e:
                    print(f"[-] Failed to sync ratings for paper {paper.id}: {e}")
        session.commit()

# Startup hook to initialize SQL tables
@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    ensure_paper_rating_columns()
    sync_existing_paper_ratings()

# Request Models
class RunStartRequest(BaseModel):
    papers: List[Dict[str, str]]
    emails_fetched: int = 0

class FeedbackRequest(BaseModel):
    feedback: str

class ProfileSaveRequest(BaseModel):
    content: str

class ModelLoadRequest(BaseModel):
    model_key: str

class ModelSettingsRequest(BaseModel):
    model_key: str
    temperature: Optional[float] = None  # None clears the override (use creator guidance)
    thinking: Optional[bool] = None      # None clears the override (use REPORT_THINKING)

class FrameworkSwitchRequest(BaseModel):
    framework: str

# Endpoints
@app.get("/api/alerts")
def fetch_alerts():
    """
    Fetches the latest Scholar alert emails from Gmail and returns unique links.
    """
    try:
        alerts = get_latest_alerts_from_gmail()
        return alerts
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/runs")
def create_run(req: RunStartRequest):
    """
    Triggers a background run for retrieving and summarizing selected papers.
    """
    if not req.papers:
        raise HTTPException(status_code=400, detail="No papers selected for processing")
    try:
        db_run = start_paper_run(req.papers, req.emails_fetched)
        return {"run_id": db_run.id, "status": db_run.status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/runs")
def list_runs(session: Session = Depends(get_session)):
    """
    Returns history of runs.
    """
    stmt = select(Run).order_by(Run.timestamp.desc())
    return session.exec(stmt).all()

@app.get("/api/runs/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)):
    """
    Returns info for a specific run including associated papers.
    """
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Query papers in this run
    stmt = select(Paper).where(Paper.run_id == run_id)
    papers = session.exec(stmt).all()

    return {
        "id": run.id,
        "timestamp": run.timestamp,
        "status": run.status,
        "emails_fetched": run.emails_fetched,
        "papers_processed": run.papers_processed,
        "papers_failed": run.papers_failed,
        "papers": papers
    }

@app.get("/api/runs/{run_id}/stream")
def stream_run_logs(run_id: int):
    """
    Streams stdout output from a run in real-time via Server-Sent Events (SSE).
    """
    if run_id not in active_logs:
        # If the run isn't actively running, return a message
        def dummy_stream():
            yield "data: [Run logs are not active or run is already completed]\n\n"
        return StreamingResponse(dummy_stream(), media_type="text/event-stream")

    q = active_logs[run_id]

    def log_event_generator():
        while True:
            try:
                # Block for 0.5s to check for log entries
                chunk = q.get(timeout=0.5)
                if chunk is None:  # Sentinel value signaling end of task
                    yield "data: [EOF]\n\n"
                    break
                # Send text line by line as SSE events
                yield f"data: {chunk}\n\n"
            except queue.Empty:
                # Keep-alive event
                yield ": keep-alive\n\n"
            except Exception as e:
                yield f"data: Error during log streaming: {e}\n\n"
                break

        # Clean up queue when stream finishes
        if run_id in active_logs:
            del active_logs[run_id]

    return StreamingResponse(log_event_generator(), media_type="text/event-stream")

@app.get("/api/reports")
def list_reports(session: Session = Depends(get_session)):
    """
    Lists all successfully completed reports.
    """
    stmt = select(Paper).where(Paper.status == "success").order_by(Paper.date_processed.desc())
    return session.exec(stmt).all()

@app.post("/api/reports/upload")
def upload_pdf(file: UploadFile = File(...)):
    """
    Accepts an uploaded PDF file, saves it to a temp directory, and triggers
    an asynchronous background Run, returning the run_id.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
        
    try:
        # Create temporary directory inside REPORTS_DIR if not exists
        temp_dir = Path(config.REPORTS_DIR) / "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        
        # Save temp file
        temp_filepath = temp_dir / f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        with open(temp_filepath, "wb") as f:
            f.write(file.file.read())
            
        # Start background run
        from backend.services import start_uploaded_paper_run
        db_run = start_uploaded_paper_run(str(temp_filepath), file.filename)
        
        return {
            "status": "success",
            "run_id": db_run.id
        }
        
    except Exception as e:
        print(f"[-] Error initiating file upload run: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/{paper_id}")
def get_report(paper_id: int, session: Session = Depends(get_session)):
    """
    Reads and returns report markdown content from the local filesystem.
    """
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if not paper.report_path or not os.path.exists(paper.report_path):
        raise HTTPException(status_code=404, detail="Markdown report file not found on disk")

    try:
        report_content = Path(paper.report_path).read_text(encoding="utf-8")
        return {
            "paper": paper,
            "markdown": report_content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {e}")

@app.post("/api/reports/{paper_id}/feedback")
def evaluate_feedback(paper_id: int, req: FeedbackRequest, session: Session = Depends(get_session)):
    """
    Submits feedback to LLM, returns current profile, proposed profile, and diff.
    """
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    try:
        current_interests = ensure_interests_file()
        proposed_interests = update_user_interests(current_interests, req.feedback)

        # Calculate unified diff
        diff_lines = list(difflib.unified_diff(
            current_interests.splitlines(keepends=True),
            proposed_interests.splitlines(keepends=True),
            fromfile="user_interests.md (current)",
            tofile="user_interests.md (proposed)",
            n=3
        ))
        diff_text = "".join(diff_lines)

        return {
            "current": current_interests,
            "proposed": proposed_interests,
            "diff": diff_text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/profile")
def get_profile():
    """
    Retrieves the current raw markdown content of user_interests.md.
    """
    try:
        content = ensure_interests_file()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profile/save")
def save_profile(req: ProfileSaveRequest):
    """
    Saves the interest profile to disk and creates a timestamped backup in .backups/
    """
    try:
        # Create backups directory
        backup_dir = Path(config.INTERESTS_FILE).parent / ".backups"
        os.makedirs(backup_dir, exist_ok=True)

        # Save timestamped backup of the current state
        if Path(config.INTERESTS_FILE).exists():
            current_content = Path(config.INTERESTS_FILE).read_text(encoding="utf-8")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"user_interests.{timestamp}.md"
            backup_file.write_text(current_content, encoding="utf-8")

        # Overwrite main user interests file
        Path(config.INTERESTS_FILE).write_text(req.content, encoding="utf-8")
        return {"status": "success", "message": "Interest profile updated and backup created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/papers/failed")
def list_failed_papers(session: Session = Depends(get_session)):
    """
    Lists papers that failed during processing or were skipped by the relevance pre-filter.
    """
    stmt = select(Paper).where(Paper.status.in_(["failed", "skipped"])).order_by(Paper.date_processed.desc())
    return session.exec(stmt).all()

# Delete Endpoints
@app.delete("/api/reports/{paper_id}")
def delete_report(paper_id: int, session: Session = Depends(get_session)):
    """
    Deletes the database record of a report and removes the markdown report file from disk.
    """
    paper = session.get(Paper, paper_id)
    if not paper or paper.status != "success":
        raise HTTPException(status_code=404, detail="Report paper not found")

    # Delete file from disk
    if paper.report_path and os.path.exists(paper.report_path):
        try:
            os.remove(paper.report_path)
        except Exception as e:
            print(f"[-] Error removing report file from disk: {e}")

    session.delete(paper)
    session.commit()
    return {"status": "success", "message": "Report deleted successfully"}

@app.delete("/api/papers/failed/{paper_id}")
def delete_failed_paper(paper_id: int, session: Session = Depends(get_session)):
    """
    Deletes a failed or skipped paper log entry from the database.
    """
    paper = session.get(Paper, paper_id)
    if not paper or paper.status not in ("failed", "skipped"):
        raise HTTPException(status_code=404, detail="Failed paper record not found")

    session.delete(paper)
    session.commit()
    return {"status": "success", "message": "Failed paper record deleted"}

# LLM Framework Endpoints
@app.get("/api/framework")
def get_framework_info():
    active_run = get_active_run()
    return {
        "framework": config.get_active_framework(),
        "available": ["lmstudio", "omlx"],
        "active_run": active_run is not None,
        "active_run_id": active_run.id if active_run else None,
    }

@app.post("/api/framework/switch")
def switch_framework(req: FrameworkSwitchRequest):
    active_run = get_active_run()
    if active_run:
        raise HTTPException(
            status_code=400,
            detail="Cannot switch framework while a paper analysis run is in progress."
        )
    return StreamingResponse(
        FrameworkManager.stream_switch_framework(req.framework),
        media_type="text/event-stream"
    )

@app.get("/api/framework/switch/stream")
def stream_switch_framework(framework: str):
    active_run = get_active_run()
    if active_run:
        raise HTTPException(
            status_code=400,
            detail="Cannot switch framework while a paper analysis run is in progress."
        )
    return StreamingResponse(
        FrameworkManager.stream_switch_framework(framework),
        media_type="text/event-stream"
    )

# Server Controls
@app.get("/api/server/status")
def get_server_status():
    """
    Checks the status of the active LLM server (LM Studio or oMLX).
    """
    return FrameworkManager.get_server_status()

@app.post("/api/server/start")
def start_server():
    """
    Starts the active LLM server.
    """
    res = FrameworkManager.start_server()
    if res.get("status") == "success":
        return res
    raise HTTPException(status_code=500, detail=res.get("detail", "Failed to start server"))

@app.post("/api/server/stop")
def stop_server():
    """
    Stops the active LLM server.
    """
    res = FrameworkManager.stop_server()
    if res.get("status") == "success":
        return res
    raise HTTPException(status_code=500, detail=res.get("detail", "Failed to stop server"))

@app.post("/api/shutdown")
def shutdown_backend(background_tasks: BackgroundTasks):
    """
    Shuts down the backend FastAPI server process gracefully.
    """
    def perform_shutdown():
        import time
        import signal
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGINT)

    background_tasks.add_task(perform_shutdown)
    return {"status": "success", "detail": "Backend server is shutting down..."}

# Model Management
@app.get("/api/models")
def list_models():
    """
    Lists available local models in the active framework and identifies loaded models.
    """
    return FrameworkManager.list_models()

def _model_settings_payload(model_key: str):
    return {
        "model_key": model_key,
        "guidance": model_settings.get_creator_guidance(model_key),
        "overrides": model_settings.get_overrides(model_key),
        "effective": model_settings.resolve_report_settings(model_key),
        "env_defaults": {"temperature": config.REPORT_TEMPERATURE, "thinking": config.REPORT_THINKING},
    }

@app.get("/api/model-settings")
def get_model_settings(model_key: str):
    """
    Full paper analysis settings for a model: creator guidance, user overrides and the
    effective values (docs/agent/decisions/0002, 0004).
    """
    return _model_settings_payload(model_key)

@app.put("/api/model-settings")
def update_model_settings(req: ModelSettingsRequest):
    """
    Stores per-model overrides for the full paper analysis. Null fields clear the override.
    """
    if req.temperature is not None and not (0.0 <= req.temperature <= 2.0):
        raise HTTPException(status_code=400, detail="Temperature must be between 0 and 2.")
    model_settings.set_overrides(req.model_key, temperature=req.temperature, thinking=req.thinking)
    return _model_settings_payload(req.model_key)

@app.post("/api/models/load")
def load_model(req: ModelLoadRequest):
    """
    Loads or unloads the selected model in the active framework.
    """
    gen = FrameworkManager.stream_load_model(req.model_key)
    last_msg = ""
    for chunk in gen:
        last_msg = chunk
    if "[ERROR]" in last_msg:
        raise HTTPException(status_code=500, detail=last_msg)
    return {"status": "success", "loaded": req.model_key}

@app.get("/api/models/load/stream")
def stream_load_model(model_key: str):
    """
    SSE stream endpoint to unload existing models and load the selected one.
    """
    return StreamingResponse(
        FrameworkManager.stream_load_model(model_key),
        media_type="text/event-stream"
    )

# Serve built frontend static files & SPA client routing
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))

if os.path.exists(frontend_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_path, "assets")), name="static_assets")

    @app.get("/{catchall:path}")
    def serve_spa(catchall: str):
        # Allow API endpoints to fall through (FastAPI handles routing precedence naturally)
        if catchall.startswith("api"):
            raise HTTPException(status_code=404, detail="API endpoint not found")

        index_file = os.path.join(frontend_path, "index.html")
        if os.path.exists(index_file):
            return FileResponse(
                index_file,
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
        return {"detail": "Vite frontend not built yet. Compile with npm run build."}
else:
    @app.get("/{catchall:path}")
    def serve_fallback(catchall: str):
        if catchall.startswith("api"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        return {"detail": "Developer Mode: Frontend build folder 'frontend/dist' not found. Please run the Vite dev server on port 5173."}
