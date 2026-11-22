import pytest

import config


@pytest.fixture(autouse=True)
def isolate_web_search(tmp_path, monkeypatch):
    """No test may read the real Tavily key or write to the real search log."""
    monkeypatch.setattr(config, "TAVILY_KEY_PATH", tmp_path / "no-key-folder" / "tavily_key")
    monkeypatch.setattr(config, "WEB_SEARCH_LOG_PATH", str(tmp_path / "web_search_log.jsonl"))
