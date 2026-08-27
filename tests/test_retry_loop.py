import uuid
from pathlib import Path

import pytest

from backend import retry_loop
from backend.models import Attempt

JOB = {"url": "https://fixture.test/shop", "json_schema": {"type": "object"}, "prompt": "get things"}


class FakeDB:
    """Records every write. No MySQL in a unit test."""

    def __init__(self, cached=None):
        self.status = None
        self.error = None
        self.attempts = []
        self.cached = cached
        self.lookups = []

    def set_status(self, job_id, status, *, error=None):
        self.status, self.error = status, error

    def get_job(self, job_id):
        return dict(JOB)

    def find_cached_script(self, url, json_schema, prompt):
        self.lookups.append((url, json_schema, prompt))
        return self.cached

    def add_attempt(self, job_id, n, code, error, output, success):
        self.attempts.append({"n": n, "code": code, "error": error, "success": success})


def _attempt(ok: bool, tag: str) -> Attempt:
    return Attempt(code=f"# {tag}", output=[{"a": 1}] if ok else None,
                   error=None if ok else f"{tag} broke", success=ok)


@pytest.fixture
def rig(monkeypatch):
    """Stub the three modules retry_loop orchestrates (rules.md E22, E23)."""
    fake = FakeDB()
    calls = {"recon": 0, "generate": []}
    monkeypatch.setattr(retry_loop, "db", fake)

    def fake_recon(url, **kw):
        calls["recon"] += 1
        return "RECON"

    def fake_generate(rec, schema, prompt, prior=None):
        calls["generate"].append(prior)
        return f"# script {len(calls['generate'])}"

    monkeypatch.setattr(retry_loop.recon, "recon", fake_recon)
    monkeypatch.setattr(retry_loop.generate, "generate", fake_generate)
    return fake, calls


def _outcomes(monkeypatch, *results):
    """Make executor.execute return the given Attempts in order."""
    seq = iter(results)
    monkeypatch.setattr(retry_loop.executor, "execute", lambda *a, **k: next(seq))


def test_first_attempt_succeeds(rig, monkeypatch):
    fake, calls = rig
    _outcomes(monkeypatch, _attempt(True, "a1"))
    retry_loop.run_job(uuid.uuid4())
    assert fake.status == "done" and fake.error is None
    assert [a["n"] for a in fake.attempts] == [1]
    assert calls["recon"] == 1


def test_third_attempt_succeeds_and_errors_are_fed_back(rig, monkeypatch):
    fake, calls = rig
    _outcomes(monkeypatch, _attempt(False, "a1"), _attempt(False, "a2"), _attempt(True, "a3"))
    retry_loop.run_job(uuid.uuid4())

    assert fake.status == "done"
    assert [a["n"] for a in fake.attempts] == [1, 2, 3]
    # The behaviour that makes the product work: each call sees the last failure.
    priors = calls["generate"]
    assert priors[0] is None
    assert priors[1].error == "a1 broke"
    assert priors[2].error == "a2 broke"
    assert calls["recon"] == 1          # recon runs once, not per attempt


def test_exhaustion_surfaces_the_last_error(rig, monkeypatch):
    fake, _ = rig
    _outcomes(monkeypatch, *(_attempt(False, f"a{n}") for n in (1, 2, 3)))
    retry_loop.run_job(uuid.uuid4())
    assert fake.status == "failed" and fake.error == "a3 broke"
    assert len(fake.attempts) == 3


def test_no_fourth_attempt(rig, monkeypatch):
    fake, calls = rig
    _outcomes(monkeypatch, *(_attempt(False, f"a{n}") for n in (1, 2, 3)))
    retry_loop.run_job(uuid.uuid4())
    assert len(calls["generate"]) == retry_loop.MAX_ATTEMPTS == 3


def test_recon_failure_stops_before_generation(rig, monkeypatch):
    fake, calls = rig
    monkeypatch.setattr(retry_loop.recon, "recon",
                        lambda url, **kw: (_ for _ in ()).throw(TimeoutError("nav timeout")))
    retry_loop.run_job(uuid.uuid4())
    assert fake.status == "failed"
    assert "recon failed for https://fixture.test/shop: nav timeout" in fake.error
    assert fake.attempts == [] and calls["generate"] == []


def test_unexpected_crash_still_lands_in_failed(rig, monkeypatch):
    fake, _ = rig
    monkeypatch.setattr(retry_loop.generate, "generate",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("api exploded")))
    retry_loop.run_job(uuid.uuid4())
    assert fake.status == "failed"          # never stuck in "running"
    assert "RuntimeError: api exploded" in fake.error


# --- reusing a saved script ------------------------------------------------

def _explode(name):
    return lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"{name} must not run"))


def test_cache_hit_skips_recon_and_the_llm(rig, monkeypatch):
    """The whole point: a repeat job costs no browser launch and no tokens."""
    fake, calls = rig
    fake.cached = "# saved script"
    monkeypatch.setattr(retry_loop.recon, "recon", _explode("recon"))
    monkeypatch.setattr(retry_loop.generate, "generate", _explode("generate"))
    _outcomes(monkeypatch, _attempt(True, "replay"))

    retry_loop.run_job(uuid.uuid4())

    assert fake.status == "done" and fake.error is None
    assert [a["n"] for a in fake.attempts] == [0]       # 0 == replayed
    assert fake.lookups == [(JOB["url"], JOB["json_schema"], JOB["prompt"])]


def test_stale_cache_falls_through_and_repairs(rig, monkeypatch):
    """A cached script that no longer works must not be a dead end."""
    fake, calls = rig
    fake.cached = "# stale script"
    _outcomes(monkeypatch, _attempt(False, "replay"), _attempt(True, "a1"))

    retry_loop.run_job(uuid.uuid4())

    assert fake.status == "done"
    assert [a["n"] for a in fake.attempts] == [0, 1]
    assert calls["recon"] == 1
    # The failed replay is what attempt 1 gets told to fix.
    assert calls["generate"][0].error == "replay broke"


def test_replay_does_not_spend_an_llm_attempt(rig, monkeypatch):
    """Attempt 0 is free, so all three generation attempts remain (rules.md C14)."""
    fake, calls = rig
    fake.cached = "# stale script"
    _outcomes(monkeypatch, *(_attempt(False, f"a{n}") for n in range(4)))

    retry_loop.run_job(uuid.uuid4())

    assert fake.status == "failed"
    assert len(calls["generate"]) == retry_loop.MAX_ATTEMPTS == 3
    assert [a["n"] for a in fake.attempts] == [0, 1, 2, 3]


def test_orchestrator_imports_nothing_it_orchestrates_with(rig):
    """rules.md B6 -- retry_loop calls the three modules, it does not reach past them."""
    src = (Path(__file__).parents[1] / "backend" / "retry_loop.py").read_text()
    for banned in ("import anthropic", "import playwright", "import subprocess"):
        assert banned not in src
