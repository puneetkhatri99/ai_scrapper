"""Suite-wide guarantee: no test ever reaches a real LLM account.

generate.py reads the key at call time, so a developer with GEMINI_API_KEY
exported would otherwise run the suite against their real credentials the
moment a stub was forgotten (rules.md E22). Overriding it here means a missed
stub fails with a 401 from a fake key instead of spending money.
"""
import pytest


@pytest.fixture(autouse=True)
def _fake_llm_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-a-real-one")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
