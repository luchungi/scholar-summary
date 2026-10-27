"""
Tests for the LLM teardown that runs before the backend is killed (decision 0011).

All tests here are offline: the framework backends are stubbed, so no `lms`/`omlx`
binary is invoked and no server is contacted. The run-marking tests use a throwaway
sqlite file rather than the project database.
"""

import sys
from pathlib import Path

import pytest
from sqlmodel import SQLModel, Session, create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
import backend.services as services
import backend.framework_manager as fm
from backend.framework_manager import FrameworkManager
from backend.models import Run


class StubBackend:
    """Stands in for LMStudioBackend / OMLXBackend, recording the calls made."""

    def __init__(self, loaded=None, unload_ok=True, stop_ok=True):
        self.loaded = loaded
        self.unload_res = {"status": "success", "detail": "ok"} if unload_ok \
            else {"status": "error", "detail": "lms: command not found"}
        self.stop_res = {"status": "success", "detail": "ok"} if stop_ok \
            else {"status": "error", "detail": "timed out"}
        self.calls = []

    def get_loaded_model(self):
        self.calls.append("get_loaded_model")
        return self.loaded

    def unload_models(self):
        self.calls.append("unload_models")
        return self.unload_res

    def stop_server(self):
        self.calls.append("stop_server")
        return self.stop_res

    # only stream_switch_framework needs these
    def get_status(self):
        return {"status": "ON"}

    def start_server(self):
        return {"status": "success", "detail": "started"}


@pytest.fixture
def stub(monkeypatch):
    """Routes FrameworkManager at a stub and removes the inter-step sleep."""
    backend = StubBackend()
    monkeypatch.setattr(FrameworkManager, "get_backend",
                        classmethod(lambda cls, framework=None: backend))
    monkeypatch.setattr(fm.time, "sleep", lambda *_: None)
    return backend


def teardown_lines(framework):
    return [line.replace("data: ", "").strip()
            for line in FrameworkManager.stream_teardown(framework) if line.strip()]


# --- stream_teardown ---

def test_unloads_then_stops_when_a_model_is_resident(stub):
    stub.loaded = "qwen3-27b"
    lines = teardown_lines("lmstudio")
    assert stub.calls == ["get_loaded_model", "unload_models", "stop_server"]
    assert any("qwen3-27b" in line for line in lines)
    assert not any("[WARNING]" in line for line in lines)


def test_skips_the_unload_when_nothing_is_resident(stub):
    stub.loaded = None
    lines = teardown_lines("omlx")
    assert "unload_models" not in stub.calls
    assert "stop_server" in stub.calls, "the server must be stopped either way"
    assert any("no model loaded" in line.lower() for line in lines)


def test_a_failed_unload_warns_but_still_stops_the_server(stub):
    """0011.7: teardown failures never abort the sequence."""
    stub.loaded = "m1"
    stub.unload_res = {"status": "error", "detail": "lms: command not found"}
    lines = teardown_lines("lmstudio")
    assert any("[WARNING]" in line and "command not found" in line for line in lines)
    assert "stop_server" in stub.calls
    assert not any("[ERROR]" in line for line in lines), \
        "[ERROR] would stop the frontend from proceeding to the kill"


def test_a_failed_server_stop_warns_and_the_generator_completes(stub):
    stub.loaded = "m1"
    stub.stop_res = {"status": "error", "detail": "timed out"}
    lines = teardown_lines("lmstudio")
    assert any("[WARNING]" in line and "timed out" in line for line in lines)
    assert not any("[ERROR]" in line for line in lines)


def test_teardown_never_emits_the_success_sentinel_itself(stub):
    """The endpoint appends [SUCCESS]; the switch path must not see it mid-stream."""
    stub.loaded = "m1"
    assert not any("[SUCCESS]" in line for line in teardown_lines("lmstudio"))


# --- the switch path still consumes the shared teardown (0011.8) ---

def test_switch_framework_runs_the_shared_teardown_once(stub, monkeypatch):
    stub.loaded = "m1"
    monkeypatch.setattr(fm, "update_env_framework", lambda f: None)
    monkeypatch.setattr(fm, "update_env_model", lambda f, m: None)
    monkeypatch.setattr(config, "set_active_framework", lambda f: None)
    monkeypatch.setattr(config, "set_active_model", lambda m: None)
    monkeypatch.setattr(config, "get_active_framework", lambda: "lmstudio")

    lines = [line.replace("data: ", "").strip()
             for line in FrameworkManager.stream_switch_framework("omlx") if line.strip()]

    assert any("Unloading active model 'm1'" in line for line in lines)
    assert stub.calls.count("unload_models") == 1
    assert stub.calls.count("stop_server") == 1
    assert lines[-1] == "[SUCCESS]"
    assert not any("/4" in line for line in lines), "step count is 3 since teardown merged"


# --- mark_active_run_interrupted (0011.5) ---

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(services, "engine", engine)
    monkeypatch.setattr(services, "_active_run_id", None)
    return engine


def _make_run(engine, status):
    with Session(engine) as session:
        run = Run(status=status)
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id


def test_no_active_run_is_a_no_op(temp_db):
    assert services.mark_active_run_interrupted() is None


def test_a_running_row_is_marked_failed(temp_db):
    run_id = _make_run(temp_db, "running")
    services._set_active_run(run_id)

    assert services.mark_active_run_interrupted() == run_id
    with Session(temp_db) as session:
        assert session.get(Run, run_id).status == "failed"
    assert services.get_active_run() is None
    assert services.mark_active_run_interrupted() is None, "second call is a no-op"


def test_a_finished_row_is_left_alone(temp_db):
    run_id = _make_run(temp_db, "completed")
    services._set_active_run(run_id)

    assert services.mark_active_run_interrupted() is None
    with Session(temp_db) as session:
        assert session.get(Run, run_id).status == "completed"
