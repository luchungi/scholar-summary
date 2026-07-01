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
    active_logs
)
import agent
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
    Lists papers that failed during processing.
    """
    stmt = select(Paper).where(Paper.status == "failed").order_by(Paper.date_processed.desc())
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
    Deletes a failed paper log entry from the database.
    """
    paper = session.get(Paper, paper_id)
    if not paper or paper.status != "failed":
        raise HTTPException(status_code=404, detail="Failed paper record not found")

    session.delete(paper)
    session.commit()
    return {"status": "success", "message": "Failed paper record deleted"}

# Helper to get Ollama base REST URL (stripping /v1)
def get_ollama_host() -> str:
    from urllib.parse import urlparse
    parsed = urlparse(config.OLLAMA_BASE_URL)
    return f"{parsed.scheme}://{parsed.netloc}"

# Helper to modify .env file
def update_env_file(model_key: str):
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        updated = False
        for idx, line in enumerate(lines):
            if line.strip().startswith("OLLAMA_MODEL="):
                lines[idx] = f"OLLAMA_MODEL=openai:{model_key}"
                updated = True
                break
        if not updated:
            lines.append(f"OLLAMA_MODEL=openai:{model_key}")
        # Clean up any leftover LM_STUDIO_MODEL lines to prevent conflicts
        lines = [line for line in lines if not line.strip().startswith("LM_STUDIO_MODEL=")]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

# Helper to check currently loaded model in memory
def get_loaded_model_in_memory() -> Optional[str]:
    try:
        import requests
        res = requests.get(f"{get_ollama_host()}/api/ps", timeout=2)
        if res.status_code == 200:
            data = res.json()
            models = data.get("models", [])
            if models:
                return models[0]["name"]
    except Exception as e:
        print(f"[-] Error querying Ollama loaded models: {e}")
    return None

# Ollama Server Controls
@app.get("/api/server/status")
def get_server_status():
    """
    Checks the status of the Ollama server by checking if the port responds.
    """
    try:
        import requests
        res = requests.get(f"{get_ollama_host()}/api/tags", timeout=2)
        if res.status_code == 200:
            return {"status": "ON"}
        return {"status": "OFF"}
    except Exception as e:
        return {"status": "OFF"}

@app.post("/api/server/start")
def start_server():
    """
    Starts the Ollama server on macOS.
    """
    try:
        status = get_server_status()
        if status["status"] == "ON":
            return {"status": "success", "detail": "Ollama is already running."}

        # Try launching the Ollama macOS application first
        res = subprocess.run("open -a Ollama", shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            return {"status": "success", "detail": "Ollama application started."}

        # Fallback to starting the CLI service in the background
        subprocess.Popen("ollama serve > /dev/null 2>&1 &", shell=True)
        return {"status": "success", "detail": "Ollama background service launched."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/server/stop")
def stop_server():
    """
    Stops the Ollama server on macOS.
    """
    try:
        subprocess.run("killall Ollama", shell=True, capture_output=True)
        subprocess.run("pkill -f 'ollama serve'", shell=True, capture_output=True)
        return {"status": "success", "detail": "Ollama server stopped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

# Ollama Model Management
@app.get("/api/models")
def list_ollama_models():
    """
    Lists available local models in Ollama using the REST API.
    """
    try:
        import requests
        loaded_in_mem = get_loaded_model_in_memory()

        res = requests.get(f"{get_ollama_host()}/api/tags", timeout=2)
        if res.status_code != 200:
            raise Exception("Failed to contact Ollama tags endpoint")

        data = res.json()
        models = []
        for item in data.get("models", []):
            name = item["name"]
            size_bytes = item.get("size", 0)

            # Format size nicely
            if size_bytes >= 1e9:
                size_str = f"{size_bytes / 1e9:.1f} GB"
            elif size_bytes >= 1e6:
                size_str = f"{size_bytes / 1e6:.1f} MB"
            else:
                size_str = f"{size_bytes} Bytes"

            is_loaded = (loaded_in_mem == name)

            models.append({
                "key": name,
                "size": size_str,
                "loaded": is_loaded
            })
        return models
    except Exception as e:
        print(f"[-] Error listing Ollama models: {e}")
        current_model = config.OLLAMA_MODEL.replace("openai:", "") if config.OLLAMA_MODEL else "None"
        return [{"key": current_model, "size": "Unknown", "loaded": True}]

@app.post("/api/models/load")
def load_ollama_model(req: ModelLoadRequest, background_tasks: BackgroundTasks):
    """
    Commands Ollama to load the selected model, updating the env config in memory and on disk.
    """
    try:
        import requests
        loaded_model = get_loaded_model_in_memory()

        if req.model_key == "none":
            if loaded_model:
                requests.post(f"{get_ollama_host()}/api/generate", json={"model": loaded_model, "keep_alive": 0}, timeout=5)
            config.OLLAMA_MODEL = ""
            update_env_file("")
            return {"status": "success", "loaded": "none"}

        if loaded_model == req.model_key:
            config.OLLAMA_MODEL = f"openai:{req.model_key}"
            update_env_file(req.model_key)
            return {"status": "success", "loaded": req.model_key}

        # If another model is active, unload it first
        if loaded_model:
            requests.post(f"{get_ollama_host()}/api/generate", json={"model": loaded_model, "keep_alive": 0}, timeout=5)

        # Update config dynamically in Python memory
        config.OLLAMA_MODEL = f"openai:{req.model_key}"
        # Update .env file
        update_env_file(req.model_key)

        # Preload model via /api/generate
        res = requests.post(f"{get_ollama_host()}/api/generate", json={"model": req.model_key}, timeout=60)
        if res.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Ollama API failed to load model: {res.text}")

        return {"status": "success", "loaded": req.model_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/models/load/stream")
def stream_load_model(model_key: str):
    """
    SSE stream endpoint to unload existing models and load the selected one.
    """
    def load_generator():
        yield "data: Checking currently loaded models in memory...\n\n"
        loaded_model = get_loaded_model_in_memory()

        if model_key == "none":
            if loaded_model:
                yield f"data: Active model in memory is '{loaded_model}'. Unloading...\n\n"
                try:
                    import requests
                    requests.post(f"{get_ollama_host()}/api/generate", json={"model": loaded_model, "keep_alive": 0}, timeout=5)
                    yield "data: Unloaded model successfully.\n\n"
                    config.OLLAMA_MODEL = ""
                    update_env_file("")
                    yield "data: [SUCCESS]\n\n"
                except Exception as e:
                    yield f"data: [ERROR] Error unloading model: {e}\n\n"
            else:
                yield "data: No active model in memory to unload.\n\n"
                config.OLLAMA_MODEL = ""
                update_env_file("")
                yield "data: [SUCCESS]\n\n"
            return

        if loaded_model == model_key:
            yield f"data: Model '{model_key}' is already loaded in memory. Skipping reload.\n\n"
            try:
                config.OLLAMA_MODEL = f"openai:{model_key}"
                update_env_file(model_key)
            except Exception as e:
                yield f"data: Error updating environment variables: {e}\n\n"
            yield "data: [SUCCESS]\n\n"
            return

        if loaded_model:
            yield f"data: Active model in memory is '{loaded_model}'. Unloading first...\n\n"
            try:
                import requests
                requests.post(f"{get_ollama_host()}/api/generate", json={"model": loaded_model, "keep_alive": 0}, timeout=5)
                yield "data: Unloaded previous model successfully.\n\n"
            except Exception as e:
                yield f"data: Error unloading current model: {e}\n\n"
        else:
            yield "data: No models currently active in memory.\n\n"

        yield f"data: Executing command to load '{model_key}' into memory...\n\n"
        try:
            import json
            import requests
            response = requests.post(
                f"{get_ollama_host()}/api/generate",
                json={"model": model_key},
                stream=True,
                timeout=120
            )

            if response.status_code != 200:
                yield f"data: [ERROR] Failed to load model. API status code: {response.status_code}\n\n"
                return

            for line in response.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    try:
                        data = json.loads(decoded)
                        status_msg = data.get("status")
                        if status_msg:
                            completed = data.get("completed", 0)
                            total = data.get("total", 0)
                            if total > 0:
                                percent = (completed / total) * 100
                                yield f"data: {status_msg}: {percent:.1f}% ({completed}/{total})\n\n"
                            else:
                                yield f"data: {status_msg}\n\n"
                        elif data.get("done", False):
                            reason = data.get("done_reason")
                            yield f"data: Model load completed. Reason: {reason or 'loaded'}\n\n"
                    except Exception as json_err:
                        yield f"data: {decoded}\n\n"

            config.OLLAMA_MODEL = f"openai:{model_key}"
            update_env_file(model_key)
            yield f"data: Successfully loaded model '{model_key}'!\n\n"
            yield "data: [SUCCESS]\n\n"
        except Exception as e:
            yield f"data: [ERROR] Exception during model load: {e}\n\n"

    return StreamingResponse(load_generator(), media_type="text/event-stream")

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
