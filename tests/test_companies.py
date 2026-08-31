"""The loan-officer directory: the CSV import, the officer upsert, and the one
guarantee the two buttons rest on -- that a manual run cannot reach the model.
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import guardrails
from backend.companies import db, runner, seed
from backend.main import app

# Five real rows from the brokers sheet, kept here rather than pointed at the
# sheet itself. The real file is a one-off input that gets renamed and moved;
# a test that skips when it does is a test that protects nothing. These five
# carry every shape the parser has to survive -- including the misaligned
# header, which is the reason seed.py reads by position and not by name.
CSV = Path(__file__).parent / "fixtures" / "brokers.csv"
client = TestClient(app)


# --- the CSV import ---------------------------------------------------------

@pytest.fixture(scope="module")
def parsed():
    return {c["name"]: c for c in seed.parse(CSV)}


def test_a_method_that_is_a_url_becomes_the_directory(parsed):
    row = parsed["Cross Country Mortgage"]
    assert row["directory_url"] == "https://crosscountrymortgage.com/mortgage/find-a-loan-officer/"
    assert row["note"] is None
    assert row["nmls_id"] == "3029" and row["lo_count"] == 4136


def test_a_method_that_is_not_a_url_becomes_a_note(parsed):
    """"Search Button" is an instruction for the model, not somewhere to go."""
    row = parsed["New American Funding, LLC"]
    assert row["note"] == "Search Button"
    assert row["directory_url"] is None
    assert row["company_url"] == "https://www.newamericanfunding.com/"


def test_a_row_with_no_urls_still_imports(parsed):
    """The batch reports it as skipped; dropping it here would hide it."""
    row = parsed["Family First Funding LLC"]
    assert row["company_url"] is None and row["directory_url"] is None
    assert row["lo_count"] is None


def test_the_header_row_is_not_a_company(parsed):
    assert "Brokerage Company Name" not in parsed
    assert len(parsed) == 5


def test_a_company_with_no_nmls_is_still_a_company(parsed):
    """Canopy has no licence number in the sheet. The column is nullable for
    exactly this, and the unique key is the name."""
    assert parsed["Canopy Mortgage"]["nmls_id"] is None
    assert parsed["Canopy Mortgage"]["directory_url"] == "https://canopymortgage.com/"


# --- companies + the officer upsert (real MySQL) ----------------------------

@pytest.fixture
def company():
    """One throwaway company. Its officers cascade away with it."""
    company_id = db.create_company({
        "name": f"test-co-{uuid.uuid4()}", "nmls_id": "1", "lo_count": 2,
        "company_url": "https://fixture.test/", "directory_url": None,
        "note": None, "sheet_url": None,
    })
    yield db.get_company(company_id)
    db.delete_company(company_id)


def _officers(company_id):
    return {o["dedupe_key"]: o for o in db.list_officers(100, 0, company_id)}


def test_an_officer_seen_twice_is_one_row_with_a_moved_clock(company):
    """The pair the user asked for: fetched_at is the first sighting and never
    moves; updated_at is when their details last actually changed."""
    row = {"name": "Ada Byron", "nmls_id": "998877", "email": "ada@example.com",
           "phone": "555-0100", "address": "1 Main St", "position": "Loan Officer"}
    db.upsert_officers(company["id"], "https://fixture.test/team", [row])
    first = _officers(company["id"])["998877"]

    db.upsert_officers(company["id"], "https://fixture.test/team",
                       [{**row, "email": "ada.byron@example.com"}])
    after = _officers(company["id"])

    assert len(after) == 1, "the same officer must not be inserted twice"
    assert after["998877"]["email"] == "ada.byron@example.com"
    assert after["998877"]["fetched_at"] == first["fetched_at"]
    assert after["998877"]["updated_at"] > first["updated_at"]


def test_an_unchanged_officer_does_not_move_updated_at(company):
    """Otherwise "when updated" would just mean "when the batch last ran"."""
    row = {"name": "Grace Hopper", "nmls_id": "112233", "email": "g@example.com",
           "phone": None, "address": None, "position": "Branch Manager"}
    db.upsert_officers(company["id"], "https://fixture.test/team", [row])
    first = _officers(company["id"])["112233"]

    # Still one kept row: `kept` counts what got past the rail, not what MySQL
    # touched. A caller must not read an idempotent re-run as a failed harvest.
    assert db.upsert_officers(company["id"], "https://fixture.test/team", [row]) == (1, [])
    assert _officers(company["id"])["112233"]["updated_at"] == first["updated_at"]


def test_an_officer_with_no_nmls_id_dedupes_on_their_name(company):
    """Most sites do not print the licence number on the listing page."""
    rows = [{"name": "No Licence", "nmls_id": "", "email": "a@example.com",
             "phone": None, "address": None, "position": None},
            {"name": "Has Licence", "nmls_id": "445566", "email": "b@example.com",
             "phone": None, "address": None, "position": None}]
    db.upsert_officers(company["id"], "https://fixture.test/team", rows)
    db.upsert_officers(company["id"], "https://fixture.test/team", rows)

    keys = _officers(company["id"])
    assert set(keys) == {"No Licence", "445566"}


def test_the_officer_rail_stands_between_a_scrape_and_the_table(company):
    """The junk a real card selector catches never becomes a person, and the
    reason comes back so the caller can act on it."""
    kept, rejected = db.upsert_officers(company["id"], "https://fixture.test/team", [
        {"name": "", "nmls_id": "", "email": "ghost@example.com"},
        {"name": "Load More"},
        {"name": "Bad Parse", "nmls_id": "41580602169219"},
        {"name": "Real Person", "nmls_id": ""},
    ])

    assert (kept, len(rejected)) == (1, 3)
    assert set(_officers(company["id"])) == {"Real Person"}


def test_scraped_whitespace_is_collapsed_before_it_becomes_a_key(company):
    """Real pages are full of &nbsp;. "Jane\xa0Doe" and "Jane Doe" are one
    person, and keying on the raw string makes them two on the next run."""
    db.upsert_officers(company["id"], "https://fixture.test/team",
                       [{"name": "Jane\xa0 Doe", "nmls_id": "", "position": " Loan  Officer "}])
    db.upsert_officers(company["id"], "https://fixture.test/team",
                       [{"name": "Jane Doe", "nmls_id": ""}])

    officers = _officers(company["id"])
    assert set(officers) == {"Jane Doe"}
    # And the second, thinner row did not delete what the first one found.
    assert officers["Jane Doe"]["position"] == "Loan Officer"


def test_the_list_carries_the_officer_count_and_last_error(company):
    db.upsert_officers(company["id"], "https://fixture.test/team",
                       [{"name": "Someone", "nmls_id": "7"}])
    db.set_company_run(company["id"], None, "no script yet -- generate one first")

    row = next(c for c in db.list_companies() if c["id"] == company["id"])
    assert row["officers"] == 1
    assert row["last_error"] == "no script yet -- generate one first"


# --- the batch --------------------------------------------------------------

class FakeJobsDB:
    """jobs.db, recorded. No MySQL, no browser, no model."""

    def __init__(self, cached=None, status="done", output=None):
        self.cached, self.status = cached, status
        self.output = output if output is not None else [{"name": "Ada", "nmls_id": "1"}]
        self.created = []

    def find_cached_script(self, url, json_schema, prompt):
        return self.cached

    def create_job(self, url, json_schema, prompt, name=None):
        job_id = uuid.uuid4()
        self.created.append({"id": job_id, "url": url, "prompt": prompt, "name": name})
        return job_id

    def get_job(self, job_id):
        return {"status": self.status, "error": None if self.status == "done" else "it broke"}

    def get_attempts(self, job_id):
        return [{"success": self.status == "done", "output_json": self.output}]


@pytest.fixture
def batch(monkeypatch):
    """Stub everything below runner: jobs.db, run_job, and the companies table."""
    jobs_db = FakeJobsDB()
    calls, written, runs = [], [], []

    monkeypatch.setattr(runner, "jobs_db", jobs_db)
    monkeypatch.setattr(runner.retry_loop, "run_job",
                        lambda job_id, script=None, row_check=None:
                            calls.append((script, row_check)))
    monkeypatch.setattr(runner.cdb, "upsert_officers",
                        lambda cid, url, rows: written.append((url, rows)) or len(rows))
    monkeypatch.setattr(runner.cdb, "set_company_run",
                        lambda cid, job_id, error: runs.append(error))
    return jobs_db, calls, written, runs


def _listing(monkeypatch, *companies):
    monkeypatch.setattr(runner.cdb, "list_companies", lambda: list(companies))


def _co(**kw):
    return {"id": uuid.uuid4(), "name": "Test Co", "directory_url": None,
            "company_url": "https://fixture.test/", "note": None,
            "last_error": None, **kw}


def test_a_manual_run_replays_the_saved_script_and_never_generates(batch, monkeypatch):
    """The whole promise of the Run all button, as one assertion: run_job is
    called *with* the script, which is the path that cannot reach the model."""
    jobs_db, calls, written, _ = batch
    jobs_db.cached = "def run(page):\n    return []"
    _listing(monkeypatch, _co())

    runner.run_all()

    assert [c[0] for c in calls] == [jobs_db.cached]
    # ...and the rail rode along, so a replay of a script that has since gone
    # wrong is a failed attempt rather than a silent bad harvest.
    assert calls[0][1] is guardrails.check_officer
    assert written and written[0][1] == jobs_db.output


def test_a_manual_run_skips_a_company_with_no_script(batch, monkeypatch):
    jobs_db, calls, _, runs = batch
    jobs_db.cached = None
    _listing(monkeypatch, _co())

    runner.run_all()

    assert calls == [], "no script means nothing to run, not a generation"
    assert runs == ["no script yet -- generate one first"]


def test_a_company_with_no_url_is_skipped_with_the_reason(batch, monkeypatch):
    _, calls, _, runs = batch
    _listing(monkeypatch, _co(company_url=None))

    runner.run_all()

    assert calls == []
    assert "no url" in runs[0]


def test_generate_leaves_a_working_script_alone(batch, monkeypatch):
    """Regenerating one that works is the money this feature exists to save."""
    jobs_db, calls, _, _ = batch
    jobs_db.cached = "def run(page):\n    return []"
    _listing(monkeypatch, _co(last_error=None))

    runner.generate_scripts()

    assert calls == []


def test_generate_rewrites_a_script_whose_last_run_failed(batch, monkeypatch):
    """Otherwise a stale script is a dead end: Run all keeps failing and
    Generate keeps skipping it."""
    jobs_db, calls, _, _ = batch
    jobs_db.cached = "def run(page):\n    return []"
    _listing(monkeypatch, _co(last_error="row 0 failed schema validation"))

    runner.generate_scripts()

    assert [c[0] for c in calls] == [None], "None is the recon -> generate -> repair path"


def test_one_bad_company_does_not_end_the_batch(batch, monkeypatch):
    jobs_db, calls, _, runs = batch
    jobs_db.cached = "code"
    good, bad = _co(name="good"), _co(name="bad")
    _listing(monkeypatch, bad, good)

    def boom(job_id, script=None, row_check=None):
        if len(calls) == 0:
            calls.append((script, row_check))
            raise RuntimeError("playwright fell over")
        calls.append((script, row_check))

    monkeypatch.setattr(runner.retry_loop, "run_job", boom)
    runner.run_all()

    assert len(calls) == 2, "the second company still ran"
    assert any("playwright fell over" in (r or "") for r in runs)
    assert runner.progress()["running"] is False, "the lock was handed back"


def test_a_failed_job_leaves_its_error_on_the_company(batch, monkeypatch):
    jobs_db, _, written, runs = batch
    jobs_db.cached, jobs_db.status = "code", "failed"
    _listing(monkeypatch, _co())

    runner.run_all()

    assert written == [], "a failed job has no rows to keep"
    assert runs[-1] == "it broke"


def test_the_note_reaches_the_prompt_and_the_directory_url_wins():
    """Both are reuse-key inputs, so this is also what decides a cache hit."""
    assert runner.target_url(_co(directory_url="https://a/team")) == "https://a/team"
    assert runner.build_prompt(_co()) == runner.OFFICER_PROMPT
    assert runner.build_prompt(_co(note="Search Button")).endswith("Search Button")


# --- the HTTP surface -------------------------------------------------------

def test_crud_round_trip():
    body = {"name": f"test-co-{uuid.uuid4()}", "company_url": "https://fixture.test/"}
    created = client.post("/companies", json=body)
    assert created.status_code == 201
    company_id = created.json()["id"]

    put = client.put(f"/companies/{company_id}", json={**body, "nmls_id": "4242"})
    assert put.status_code == 200
    assert next(c for c in client.get("/companies").json()
                if c["id"] == company_id)["nmls_id"] == "4242"

    assert client.delete(f"/companies/{company_id}").status_code == 204
    assert client.delete(f"/companies/{company_id}").status_code == 404


def test_a_blank_url_box_is_null_not_an_empty_string():
    body = {"name": f"test-co-{uuid.uuid4()}", "company_url": "", "note": "  "}
    company_id = client.post("/companies", json=body).json()["id"]
    try:
        row = next(c for c in client.get("/companies").json() if c["id"] == company_id)
        assert row["company_url"] is None and row["note"] is None
    finally:
        client.delete(f"/companies/{company_id}")


@pytest.mark.parametrize("url", ["ftp://fixture.test/", "not-a-url"])
def test_a_non_http_url_is_refused_at_the_boundary(url):
    r = client.post("/companies", json={"name": "x", "company_url": url})
    assert r.status_code == 422
    assert "http" in r.text


def test_a_second_run_while_one_is_going_is_a_409():
    """A click that queues an hour behind another is worse than a no.

    The claim also has to *read* as running straight away: BackgroundTasks does
    not start until the response is sent, and a poller arriving in that window
    must not conclude the batch already finished.
    """
    assert runner.claim()
    try:
        assert client.get("/companies/run").json()["running"] is True
        assert client.post("/companies/run", json={}).status_code == 409
        assert client.post("/companies/scripts", json={}).status_code == 409
    finally:
        runner._LOCK.release()

    assert client.get("/companies/run").json()["running"] is False


def test_the_rail_reaches_the_attempt_not_only_the_database(batch, monkeypatch):
    """The bug this exists to stop: a script that scrapes two licence numbers
    into one field returns schema-valid strings, so the attempt succeeds, the
    job is done, and every later run replays the same broken script. Handing
    the rail to the loop is what turns that into a repairable failed attempt."""
    jobs_db, calls, _, _ = batch
    jobs_db.cached = "code"
    _listing(monkeypatch, _co())

    runner.run_all()

    rail = calls[0][1]
    assert rail is not None, "run_job was called without the officer rail"
    assert rail({"name": "Jason Thomas", "nmls_id": "41580602169219"}) is not None
    assert rail({"name": "Erin Beckman", "nmls_id": "2142499"}) is None


def test_a_run_that_changes_nothing_is_not_an_error(batch, monkeypatch):
    """The second Run all over an unchanged site keeps every officer and writes
    no rows. That is success, and must not look like a failed harvest."""
    jobs_db, _, _, runs = batch
    jobs_db.cached = "code"
    monkeypatch.setattr(runner.cdb, "upsert_officers", lambda cid, url, rows: (len(rows), []))
    _listing(monkeypatch, _co())

    runner.run_all()

    assert runs[-1] is None
