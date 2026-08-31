"""Plan 08: the paths that only matter when something is already wrong."""
import ast
import functools
import http.server
import logging
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import config, main
from backend.jobs import db
from backend.llm import generate
from backend.scraping import recon
from backend.main import app
from tests.test_generate import RECON, SCHEMA, FakeClient

BACKEND = Path(__file__).parents[1] / "backend"


# --- 2. limits live in one place ------------------------------------------

def test_every_limit_is_named_in_config():
    assert config.MAX_ATTEMPTS == 3               # rules.md C14
    assert config.EXEC_TIMEOUT == 120
    assert config.RECON_TIMEOUT == 30
    assert config.EXEC_MEMORY_BYTES == 1_500_000_000
    assert config.MAX_PROMPT_CHARS == 4_000
    assert config.MAX_ERROR_CHARS == 4_000
    assert config.STALE_RUNNING_MIN == 10


def test_no_module_hardcodes_a_limit_config_owns():
    """A second copy of a limit is a limit that will drift."""
    for path in BACKEND.rglob("*.py"):
        if path.name == "config.py":
            continue
        src = path.read_text()
        for literal in ("1_500_000_000", "1500000000", "max_length=4000"):
            assert literal not in src, f"{path} hardcodes {literal}"


# --- 1. failure paths: the target site -------------------------------------

@pytest.fixture(scope="module")
def refusing_site():
    """Serves 403 to everything -- a bot wall, near enough."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"<html><body>Access denied</body></html>")

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/shop"
    srv.shutdown()


def test_bot_blocked_site_fails_loudly(refusing_site):
    with pytest.raises(RuntimeError) as e:
        recon.recon(refusing_site)
    assert "403" in str(e.value) and "blocked" in str(e.value)
    assert refusing_site in str(e.value)


def test_unreachable_site_fails_loudly():
    # Port 1 on loopback: nothing listens, connection refused immediately.
    with pytest.raises(Exception) as e:
        recon.recon("http://127.0.0.1:1/nothing", timeout=5)
    assert "127.0.0.1:1" in str(e.value)


# --- 1. failure paths: the database ----------------------------------------

@pytest.fixture
def db_down(monkeypatch):
    def boom(*a, **k):
        raise db.Unavailable(2003, "Can't connect to MySQL server on '127.0.0.1'")

    for fn in ("create_job", "get_job", "get_attempts", "set_status"):
        monkeypatch.setattr(db, fn, boom)


def test_post_jobs_returns_503_when_mysql_is_down(db_down):
    r = TestClient(app).post("/jobs", json={
        "url": "https://example.com", "json_schema": {"type": "object"}, "prompt": "x"})
    assert r.status_code == 503
    assert "database unavailable" in r.json()["detail"]


def test_get_job_returns_503_when_mysql_is_down(db_down):
    r = TestClient(app).get(f"/jobs/{uuid.uuid4()}")
    assert r.status_code == 503


def test_startup_survives_a_dead_database(db_down, monkeypatch, caplog):
    monkeypatch.setattr(db, "fail_stale_running", lambda *a, **k: (_ for _ in ()).throw(
        db.Unavailable(2003, "Can't connect")))
    with caplog.at_level(logging.WARNING), TestClient(app) as c:
        assert c.get("/health").status_code == 200      # the app still comes up
    assert "database unreachable" in caplog.text


# --- 1. failure paths: a process that died mid-job -------------------------

def test_stale_running_jobs_are_swept_at_startup():
    fresh = db.create_job("https://example.com", {"type": "object"}, "fresh")
    stale = db.create_job("https://example.com", {"type": "object"}, "stale")
    try:
        db.set_status(fresh, "running")
        db.set_status(stale, "running")
        with db._cur() as cur:                     # backdate past the threshold
            cur.execute("update jobs set updated_at = now() - interval %s minute where id = %s",
                        (config.STALE_RUNNING_MIN + 5, str(stale)))

        assert db.fail_stale_running() >= 1
        assert db.get_job(stale)["status"] == "failed"
        assert "interrupted" in db.get_job(stale)["error"]
        assert db.get_job(fresh)["status"] == "running"      # untouched
    finally:
        with db._cur() as cur:
            for job_id in (fresh, stale):
                cur.execute("delete from jobs where id = %s", (str(job_id),))


# --- 3. cost visibility ----------------------------------------------------

def test_token_usage_is_logged_per_call(caplog):
    """A silently broken cache costs money and raises nothing (rules.md C12)."""
    client = FakeClient("```python\ndef run(page):\n    return [{}]\n```")
    with caplog.at_level(logging.INFO, logger="backend.llm.generate"):
        generate.generate(RECON, SCHEMA, "get things", client=client)
        first = caplog.messages[-1]
        generate.generate(RECON, SCHEMA, "get things again", client=client)
        second = caplog.messages[-1]

    assert "cached=0" in first
    assert "cached=1467" in second                # the prefix was reused
    assert "input=1500" in first and "output=400" in first


# --- 5. final review gate --------------------------------------------------

# The "May NOT touch" column of architecture.md 2, as a test.
FORBIDDEN = {
    "main.py":                 {"playwright", "httpx", "anthropic", "subprocess", "pymysql"},
    "mysql.py":                {"playwright", "httpx", "anthropic", "subprocess",
                                "backend.jobs.db"},
    "contracts.py":            {"playwright", "httpx", "anthropic", "subprocess",
                                "pymysql", "backend.jobs.db"},
    "guardrails.py":           {"playwright", "httpx", "anthropic", "subprocess",
                                "pymysql", "backend.jobs.db"},
    "companies/router.py":     {"playwright", "httpx", "anthropic", "subprocess", "pymysql"},
    "companies/schemas.py":    {"playwright", "httpx", "anthropic", "subprocess",
                                "pymysql", "backend.jobs.db"},
    "companies/db.py":         {"playwright", "httpx", "anthropic", "subprocess"},
    # The batch drives jobs.retry_loop; it never opens a browser or a model itself.
    "companies/runner.py":     {"playwright", "httpx", "anthropic", "subprocess"},
    "companies/seed.py":       {"playwright", "httpx", "anthropic", "subprocess", "pymysql"},
    # The evals live in the package but are not the app. Two invariants worth
    # having a machine hold: an eval never names the database (it would then be
    # measuring the script cache instead of the model), and it never imports
    # retry_loop -- it re-implements that loop deliberately, *without* the
    # replay, and importing the real one would quietly put the cache back.
    "evals/cases.py":          {"playwright", "httpx", "anthropic", "subprocess",
                                "pymysql", "backend.jobs.db", "backend.companies.db"},
    "evals/run.py":            {"playwright", "httpx", "anthropic", "subprocess",
                                "pymysql", "backend.jobs.db", "backend.companies.db",
                                "backend.jobs.retry_loop"},
    "jobs/schemas.py":         {"playwright", "httpx", "anthropic", "subprocess",
                                "pymysql", "backend.jobs.db"},
    "jobs/router.py":          {"playwright", "httpx", "anthropic", "subprocess", "pymysql"},
    "jobs/db.py":              {"playwright", "httpx", "anthropic", "subprocess"},
    "jobs/retry_loop.py":      {"httpx", "anthropic", "playwright", "subprocess"},
    "scraping/recon.py":       {"httpx", "anthropic", "subprocess", "backend.jobs.db"},
    "scraping/executor.py":    {"httpx", "anthropic", "backend.jobs.db", "backend.llm.generate"},
    "llm/generate.py":         {"playwright", "subprocess", "backend.jobs.db",
                                "backend.scraping.executor"},
    "llm/prompts.py":          {"playwright", "httpx", "anthropic", "subprocess", "pymysql"},
}


def test_every_backend_module_is_in_the_import_table():
    """A new module with no row is a boundary nobody ever chose."""
    on_disk = {str(p.relative_to(BACKEND)) for p in BACKEND.rglob("*.py")
               if p.name not in ("__init__.py", "config.py")}
    assert on_disk == set(FORBIDDEN)


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return {n.split(".")[0] if not n.startswith("backend.") else n for n in names}


@pytest.mark.parametrize("module", sorted(FORBIDDEN))
def test_import_table_holds(module):
    assert not (_imports(BACKEND / module) & FORBIDDEN[module])


def test_generate_does_not_load_playwright_at_runtime():
    """The TYPE_CHECKING guard is the only thing keeping this true."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import backend.llm.generate, sys; print('playwright' in sys.modules)"],
        capture_output=True, text=True, cwd=BACKEND.parent,
    )
    assert out.stdout.strip() == "False", out.stderr


def test_no_swallowed_errors_anywhere():
    for path in BACKEND.rglob("*.py"):
        src = path.read_text()
        assert "except: pass" not in src and "except:\n" not in src, path.name
        assert "except Exception: pass" not in src, path.name


def test_generated_code_is_never_evaluated_in_process():
    """rules.md A1, checked across the whole package, not just executor.py."""
    for path in BACKEND.rglob("*.py"):
        src = "\n".join(l for l in path.read_text().splitlines()
                        if not l.lstrip().startswith("#"))
        for banned in ("exec(", "eval(", "importlib"):
            assert banned not in src, f"{path.name} uses {banned}"


# --- 1. failure paths: the LLM API -----------------------------------------

@pytest.mark.parametrize("status,detail", [(429, "rate limit exceeded"),
                                           (400, "model gemini-nope does not exist")])
def test_api_errors_fail_the_job_once_with_the_real_message(status, detail, monkeypatch):
    """One call, one failure, and the provider's own words reach the user.

    There is no SDK retrying underneath us any more, so this also proves we
    did not quietly add a retry layer of our own.
    """
    import httpx

    from backend.jobs import retry_loop
    from tests.test_retry_loop import FakeDB

    fake, calls = FakeDB(), []
    monkeypatch.setattr(retry_loop, "db", fake)
    monkeypatch.setattr(retry_loop.recon, "recon", lambda url, **kw: "RECON")

    request = httpx.Request("POST", generate.API_URL)

    def boom(*a, **k):
        calls.append(1)
        raise httpx.HTTPStatusError(
            f"Gemini returned {status}: {detail}",
            request=request, response=httpx.Response(status, request=request))

    monkeypatch.setattr(retry_loop.generate, "generate", boom)
    retry_loop.run_job(uuid.uuid4())

    assert fake.status == "failed"
    assert "HTTPStatusError" in fake.error
    assert str(status) in fake.error and detail in fake.error   # the real reason
    assert len(calls) == 1                 # not retried by us
    assert fake.attempts == []             # nothing ran, so nothing is recorded


def test_an_http_error_carries_the_response_body(monkeypatch):
    """A 400 whose body says *why* is the difference between a fixable job and
    an unreadable one, so the body must survive into jobs.error."""
    import httpx

    class Erroring:
        def post(self, url, *, json, headers):
            request = httpx.Request("POST", url)
            return httpx.Response(400, request=request,
                                  text='{"error":"model gemini-nope does not exist"}')

    with pytest.raises(httpx.HTTPStatusError, match="gemini-nope does not exist"):
        generate.generate(RECON, SCHEMA, "get things", client=Erroring())
