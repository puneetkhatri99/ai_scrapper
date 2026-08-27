import functools
import http.server
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import db, generate, main, retry_loop
from backend.main import app

client = TestClient(app)

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "price": {"type": "number"}},
    "required": ["name"],
}
BODY = {"url": "https://example.com/shop", "json_schema": SCHEMA, "prompt": "get the products"}


@pytest.fixture
def seeded():
    """Real MySQL, cleaned up after. Yields a maker; rows go away at teardown."""
    ids: list[uuid.UUID] = []

    def make(status: str = "pending", *, error=None, attempt=None) -> uuid.UUID:
        job_id = db.create_job(BODY["url"], SCHEMA, BODY["prompt"])
        ids.append(job_id)
        if attempt is not None:
            db.add_attempt(job_id, 1, **attempt)
        if status != "pending":
            db.set_status(job_id, status, error=error)
        return job_id

    yield make
    with db._cur() as cur:
        for job_id in ids:
            cur.execute("delete from script_attempts where job_id = %s", (str(job_id),))
            cur.execute("delete from jobs where id = %s", (str(job_id),))


@pytest.fixture
def no_background(monkeypatch):
    """Record the dispatch instead of running the whole pipeline."""
    called = []
    monkeypatch.setattr(retry_loop, "run_job", lambda job_id: called.append(job_id))
    return called


def test_post_jobs_returns_202_and_schedules_the_loop(no_background):
    r = client.post("/jobs", json=BODY)
    assert r.status_code == 202
    job_id = uuid.UUID(r.json()["job_id"])
    try:
        assert db.get_job(job_id)["status"] == "pending"
        assert no_background == [job_id]          # dispatched, exactly once
    finally:
        with db._cur() as cur:
            cur.execute("delete from jobs where id = %s", (str(job_id),))


@pytest.mark.parametrize(
    "bad",
    [
        {"url": "ftp://example.com/shop"},
        {"url": "not a url"},
        {"prompt": ""},
        {"prompt": "x" * 4001},
        {"json_schema": "not a dict"},
        {"json_schema": {"properties": {}}},      # no "type"
    ],
)
def test_post_jobs_rejects_bad_input(bad, no_background):
    assert client.post("/jobs", json={**BODY, **bad}).status_code == 422
    assert no_background == []


def test_unknown_job_is_404():
    assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/jobs/{uuid.uuid4()}/attempts").status_code == 404


def test_pending_job_has_no_result_no_error(seeded):
    body = client.get(f"/jobs/{seeded('pending')}").json()
    assert body["status"] == "pending" and body["attempts"] == 0
    assert body["result"] is None and body["script"] is None and body["error"] is None


def test_running_job_reports_attempts_so_far(seeded):
    job_id = seeded("running", attempt={"code": "# a1", "error": "boom", "output": None,
                                        "success": False})
    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "running" and body["attempts"] == 1
    assert body["result"] is None and body["script"] is None


def test_done_job_carries_result_and_script(seeded):
    rows = [{"name": "Runner One", "price": 10.0}]
    job_id = seeded("done", attempt={"code": "def run(page): ...", "error": None,
                                     "output": rows, "success": True})
    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "done" and body["attempts"] == 1
    assert body["result"] == rows and body["script"] == "def run(page): ..."
    assert body["error"] is None


def test_failed_job_carries_the_error_only(seeded):
    job_id = seeded("failed", error="row 0 failed schema validation",
                    attempt={"code": "# a3", "error": "row 0 failed schema validation",
                             "output": None, "success": False})
    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "failed" and body["error"] == "row 0 failed schema validation"
    assert body["result"] is None and body["script"] is None


def test_attempts_endpoint_returns_the_history(seeded):
    job_id = seeded("failed", error="boom", attempt={"code": "# a1", "error": "boom",
                                                     "output": None, "success": False})
    rows = client.get(f"/jobs/{job_id}/attempts").json()
    assert [r["attempt_number"] for r in rows] == [1]
    assert rows[0]["script_code"] == "# a1" and rows[0]["success"] is False


# --- end to end: real playwright, real subprocess, no Anthropic call ---------

FIXTURES = Path(__file__).parent / "fixtures"

HAND_WRITTEN = '''
def run(page):
    rows = []
    for card in page.query_selector_all("[data-testid^=product-]"):
        rows.append({
            "name": card.query_selector("h3").inner_text(),
            "price": float(card.query_selector("span").inner_text().lstrip("$")),
        })
    return rows
'''


@pytest.fixture(scope="module")
def fixture_site():
    """Local http.server -- never someone else's uptime (rules.md E23)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/shop.html"
    srv.shutdown()


def test_end_to_end_pipeline(fixture_site, monkeypatch):
    """POST -> recon -> generate -> execute -> validate -> done, actually connected."""
    monkeypatch.setattr(generate, "generate", lambda *a, **k: HAND_WRITTEN)

    r = client.post("/jobs", json={**BODY, "url": fixture_site})
    assert r.status_code == 202
    job_id = uuid.UUID(r.json()["job_id"])

    try:
        # TestClient runs BackgroundTasks before returning, so the job is settled.
        body = client.get(f"/jobs/{job_id}").json()
        assert body["status"] == "done", body["error"]
        assert body["attempts"] == 1
        assert len(body["result"]) == 10
        assert body["result"][0] == {"name": "Runner One", "price": 10.0}
        assert body["script"] == HAND_WRITTEN
    finally:
        with db._cur() as cur:
            cur.execute("delete from script_attempts where job_id = %s", (str(job_id),))
            cur.execute("delete from jobs where id = %s", (str(job_id),))


def test_main_imports_nothing_it_should_not(monkeypatch):
    src = Path(main.__file__).read_text()
    for banned in ("playwright", "anthropic", "subprocess"):
        assert banned not in src.split('"""', 2)[2]      # docstring names them


# --- browse: read-only views over both tables -------------------------------

def test_list_jobs_is_newest_first_and_counts_attempts(seeded):
    old = seeded("done", attempt={"code": "# a1", "error": None,
                                  "output": [{"name": "x"}], "success": True})
    new = seeded("pending")
    # created_at is second-precision, so two rows seeded in the same second
    # would tie and make this assert a coin flip. Age one of them on purpose.
    with db._cur() as cur:
        cur.execute("update jobs set created_at = created_at - interval 1 minute"
                    " where id = %s", (str(old),))

    rows = client.get("/jobs?limit=500").json()
    ids = [r["id"] for r in rows]
    assert ids.index(str(new)) < ids.index(str(old))     # newest first

    by_id = {r["id"]: r for r in rows}
    assert by_id[str(old)]["attempts"] == 1
    assert by_id[str(new)]["attempts"] == 0
    assert by_id[str(old)]["json_schema"] == SCHEMA      # decoded, not a string


def test_list_endpoints_honour_limit(seeded):
    for _ in range(3):
        seeded("pending")
    assert len(client.get("/jobs?limit=2").json()) == 2
    assert client.get("/jobs?limit=0").status_code == 422        # capped both ends
    assert client.get("/jobs?limit=501").status_code == 422


def test_list_attempts_carries_its_jobs_url(seeded):
    job_id = seeded("failed", error="boom", attempt={"code": "# a1", "error": "boom",
                                                     "output": None, "success": False})
    row = next(r for r in client.get("/attempts?limit=500").json()
               if r["job_id"] == str(job_id))
    assert row["url"] == BODY["url"] and row["success"] is False


def test_list_scripts_shows_saved_scripts_with_reuse_count(seeded):
    job_id = seeded("done", attempt={"code": "def run(page): ...", "error": None,
                                     "output": [{"name": "x"}], "success": True})
    row = next(r for r in client.get("/scripts?limit=500").json()
               if r["job_id"] == str(job_id))
    assert row["script_code"] == "def run(page): ..."
    assert row["url"] == BODY["url"] and row["reuse_count"] == 0

    # A replay of that same job (attempt 0) is what "reused" counts.
    db.add_attempt(seeded("done"), 0, "def run(page): ...", None, [{"name": "x"}], True)
    row = next(r for r in client.get("/scripts?limit=500").json()
               if r["job_id"] == str(job_id))
    assert row["reuse_count"] == 1


def test_end_to_end_reuses_the_saved_script(fixture_site, monkeypatch):
    """The feature, end to end: the second identical job runs the saved script
    without touching recon or the LLM."""
    monkeypatch.setattr(generate, "generate", lambda *a, **k: HAND_WRITTEN)
    body = {**BODY, "url": fixture_site, "prompt": "reuse me"}
    first = uuid.UUID(client.post("/jobs", json=body).json()["job_id"])

    def explode(*a, **k):
        raise AssertionError("a cache hit must not reach this")

    try:
        assert client.get(f"/jobs/{first}").json()["status"] == "done"

        monkeypatch.setattr(generate, "generate", explode)
        monkeypatch.setattr(retry_loop.recon, "recon", explode)
        second = uuid.UUID(client.post("/jobs", json=body).json()["job_id"])

        got = client.get(f"/jobs/{second}").json()
        assert got["status"] == "done", got["error"]
        assert got["script"] == HAND_WRITTEN
        assert len(got["result"]) == 10
        assert [r["attempt_number"] for r in
                client.get(f"/jobs/{second}/attempts").json()] == [0]
    finally:
        with db._cur() as cur:
            cur.execute("delete from script_attempts where job_id in"
                        " (select id from jobs where prompt = 'reuse me')")
            cur.execute("delete from jobs where prompt = 'reuse me'")
