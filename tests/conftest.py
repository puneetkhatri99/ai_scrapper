"""Suite-wide guarantees: no test reaches a real LLM account, and the local
fixture sites every test scrapes are reachable.

generate.py reads the key at call time, so a developer with GEMINI_API_KEY
exported would otherwise run the suite against their real credentials the
moment a stub was forgotten (rules.md E22). Overriding it here means a missed
stub fails with a 401 from a fake key instead of spending money.
"""
import pytest

from backend import config


@pytest.fixture(autouse=True)
def _fake_llm_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-a-real-one")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _allow_fixture_sites(monkeypatch):
    """Every site in this suite is a local http.server on 127.0.0.1, which the
    SSRF rail blocks by default (guardrails.check_url). Off here, exactly as a
    developer scraping a local site sets ALLOW_PRIVATE_URLS=1. test_guardrails
    turns it back on to prove the rail still bites.
    """
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", True)
