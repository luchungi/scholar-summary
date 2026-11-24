import pytest

import config


@pytest.fixture(autouse=True)
def isolate_web_search(tmp_path, monkeypatch):
    """No test may read the real Tavily key or write to the real search log."""
    monkeypatch.setattr(config, "TAVILY_KEY_PATH", tmp_path / "no-key-folder" / "tavily_key")
    monkeypatch.setattr(config, "WEB_SEARCH_LOG_PATH", str(tmp_path / "web_search_log.jsonl"))


@pytest.fixture(autouse=True)
def isolate_openreview(tmp_path, monkeypatch):
    """No test may read the real OpenReview login or share a token with another test."""
    import openreview_client

    monkeypatch.setattr(config, "OPENREVIEW_CREDENTIALS_PATH",
                        tmp_path / "no-openreview-folder" / "openreview.env")
    monkeypatch.setattr(openreview_client, "_token", None)
    monkeypatch.setattr(openreview_client, "_token_expires", 0.0)
    monkeypatch.setattr(openreview_client, "_login_failure", None)
