"""The batch: walk the broker list, run each company's scrape, keep the officers.

The scraping itself is not here. A company's scrape is an ordinary job, so this
module drives `jobs.retry_loop.run_job` and reuses recon, generation, the
sandbox and the repair loop whole. What it owns is the order of the *batch* and
the one decision that makes the two buttons mean different things:

  generate_scripts()  run_job(job_id)              -- may call the model
  run_all()           run_job(job_id, script=code) -- cannot, by construction

The second passes the saved script down the supplied-script path, which by
design executes exactly that code as attempt 0 and never falls through to the
repair loop (CLAUDE.md 8). So "a manual run never spends money" needs no flag
on the loop and no second execution path -- it is the shape of the call.

Imports jobs and companies.db only: no httpx, no playwright, no subprocess.
"""
import logging
import threading
import uuid
from typing import Any

from backend import guardrails, tracing
from backend.companies import db as cdb
from backend.jobs import db as jobs_db, retry_loop

log = logging.getLogger(__name__)

# The reuse key, and the reason both live here as frozen module constants:
# find_cached_script matches on url + prompt + schema, so a company replays its
# saved script only while these bytes stay identical. Editing either is a
# deliberate "regenerate all 66 scripts".
OFFICER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "nmls_id": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "address": {"type": "string"},
        "position": {"type": "string"},
    },
    "required": ["name"],
}

# Six fields, not nine. `source_url` is the page we pointed the browser at and
# the two timestamps are the database's -- asking a model for a value it cannot
# know is how you get a confident wrong one.
OFFICER_PROMPT = (
    "Extract every loan officer / mortgage loan originator this site lists. "
    "Work through the whole directory: follow pagination, 'next', 'load more' "
    "and infinite scroll until no new people appear, and if the listing only "
    "shows names, open each person's profile page for the rest of their "
    "details. For each person return: name, nmls_id, email, phone, address "
    "(their branch or office address), and position (their job title, e.g. "
    "'Loan Officer', 'Branch Manager'). "
    # Observed on a real directory: "NMLS# 943184 / CA DRE# 02079631". A script
    # that strips non-digits from that whole line returns 94318402079631, which
    # is not anybody's licence number -- and it is schema-valid, so nothing
    # downstream would have caught it. Naming the trap in the prompt is cheaper
    # than three repair attempts discovering it.
    "The nmls_id is digits only and is usually 6 or 7 of them. Directories "
    "often print a second, unrelated licence on the same line -- a state real "
    "estate licence such as 'CA DRE# 02079631' or 'BRE#' -- so take only the "
    "digits that follow NMLS and stop at the separator; never run two numbers "
    "together. "
    "Return an empty string for any field this site does not show. "
    "Skip anyone who is not a loan officer -- support staff, executives and "
    "realtors are not wanted."
)

# ponytail: one company at a time, in-process. 66 sequential Playwright runs is
# minutes, not a queue problem -- revisit when the list is thousands long.
_LOCK = threading.Lock()

# Where the batch has got to. Plain dict: every write is a whole-value
# assignment from the single runner thread, and the reader only displays it.
# There is deliberately no `running` key -- see progress() below.
PROGRESS: dict[str, Any] = {"phase": None, "done": 0, "total": 0, "current": None}


def claim() -> bool:
    """True if the caller now owns the batch, False if one is already going.

    Taken in the router so a second click gets a 409 immediately rather than
    queueing behind a run that takes an hour; released in `_batch`'s `finally`.
    """
    if not _LOCK.acquire(blocking=False):
        return False
    PROGRESS.update(phase=None, done=0, total=0, current=None)
    return True


def progress() -> dict[str, Any]:
    """What the poller sees.

    `running` is the lock itself rather than a flag beside it, so the two can
    never disagree. It also has to be true from the moment the router claims:
    BackgroundTasks does not start until the response has been sent, and a
    poller arriving in that window would otherwise read running=False and
    conclude the batch had finished before it began.
    """
    return {"running": _LOCK.locked(), **PROGRESS}


def target_url(company: dict) -> str | None:
    """Where this company's officers actually are.

    The directory url when the sheet had one, the company's home page
    otherwise -- and None for the handful of rows that carry neither, which the
    batch skips with that reason rather than pointing a browser at nothing.
    """
    return company.get("directory_url") or company.get("company_url") or None


def build_prompt(company: dict) -> str:
    """The frozen prompt, plus whatever the sheet's Method column said when it
    was not a url ("Search Button", "When click in header Tab Location").

    That hint is part of the reuse key, so editing a company's note is a
    deliberate request for a new script -- which is the behaviour you want when
    the note is what was wrong.
    """
    note = (company.get("note") or "").strip()
    return f"{OFFICER_PROMPT}\n\nHint about this site: {note}" if note else OFFICER_PROMPT


# --- the two entry points ---------------------------------------------------

def generate_scripts(ids: set[str] | None = None) -> None:
    """Write a script for every company that has no working one. Costs money."""
    _batch(ids, generate=True)


def run_all(ids: set[str] | None = None) -> None:
    """Replay every saved script and keep what it extracted. Costs nothing."""
    _batch(ids, generate=False)


def _batch(ids: set[str] | None, *, generate: bool) -> None:
    """Never raises: it is a BackgroundTask, so there is nobody to catch it."""
    # Already ours when the router got here through claim(), which is what let
    # it refuse a second click synchronously. A direct call -- a test, a shell
    # -- takes it here instead, so the lock is held exactly once either way.
    _LOCK.acquire(blocking=False)
    PROGRESS.update(phase="generate" if generate else "run", done=0, current=None)
    try:
        # The batch is the trace and every company nests under it, so one page
        # answers "where has it got to, and what has the whole pass spent".
        with tracing.span("generate scripts" if generate else "run all") as batch:
            companies = [c for c in cdb.list_companies()
                         if ids is None or str(c["id"]) in ids]
            PROGRESS["total"] = len(companies)
            batch.update(input={"companies": len(companies)})

            for company in companies:
                PROGRESS["current"] = company["name"]
                # A span per company, so a batch is one trace you can watch:
                # which one it is on now, how many attempts each took, what the
                # whole pass spent. A company skipped for want of a url or a
                # saved script leaves a span too -- "nothing happened, and here
                # is why" is the answer the progress line cannot give.
                with tracing.span(company["name"], input=target_url(company)):
                    try:
                        _one(company, generate=generate)
                    except Exception as e:
                        # Broad on purpose, and not swallowed (rules.md D20): 65
                        # good companies must not be lost to one bad one, and the
                        # reason lands in that company's row, where the user will
                        # look for it.
                        log.exception("company=%s failed", company["name"])
                        reason = f"{type(e).__name__}: {e}"
                        cdb.set_company_run(company["id"], None, reason)
                        tracing.update(level="ERROR", status_message=reason)
                PROGRESS["done"] += 1
    finally:
        PROGRESS.update(phase=None, current=None)
        _LOCK.release()          # and with it, progress()["running"]
        tracing.flush()


def _one(company: dict, *, generate: bool) -> None:
    url = target_url(company)
    if url is None:
        return cdb.set_company_run(
            company["id"], None, "no url -- fill in a company or directory url")

    prompt = build_prompt(company)
    saved = jobs_db.find_cached_script(url, OFFICER_SCHEMA, prompt)

    if generate:
        # A script that worked last time is not rewritten -- that is the whole
        # point of paying for one. A script whose last run failed is, which is
        # what makes "Run all, then Generate scripts" repair only the failures.
        if saved is not None and not company["last_error"]:
            return
        script = None
    else:
        if saved is None:
            return cdb.set_company_run(
                company["id"], None, "no script yet -- generate one first")
        script = saved

    job_id = jobs_db.create_job(url, OFFICER_SCHEMA, prompt, name=company["name"])
    cdb.set_company_run(company["id"], job_id, None)
    # The officer rail goes *in* to the loop, not just at the database door.
    # A script that scrapes two licence numbers into one field still returns
    # schema-valid strings, so without this the attempt succeeds, the job is
    # done, and the next Generate pass happily replays the same broken script
    # for ever. Handed to the loop, the same rejection is an ordinary failed
    # attempt and the model repairs the selector it got wrong.
    retry_loop.run_job(job_id, script, guardrails.check_officer)   # never raises

    _harvest(company, job_id, url)


def _harvest(company: dict, job_id: uuid.UUID, url: str) -> None:
    """Move the winning attempt's rows into `loan_officers`."""
    job = jobs_db.get_job(job_id)
    if job is None or job["status"] != "done":
        error = job["error"] if job else "job vanished mid-run"
        return cdb.set_company_run(company["id"], job_id, error)

    won = next((a for a in jobs_db.get_attempts(job_id) if a["success"]), None)
    rows = (won or {}).get("output_json") or []
    kept, rejected = cdb.upsert_officers(company["id"], url, rows)

    # Should be empty: the same rail already ran inside the attempt, so an
    # accepted attempt has no rejectable rows in it. What reaches here is a row
    # stored by an older run, before the rail existed or before it was this
    # strict. Loud, because it means this company is holding data the rail
    # would not accept today.
    if rejected:
        log.warning("company=%s %d/%d stored row(s) fail the officer rail: %s",
                    company["name"], len(rejected), len(rows), rejected[0])

    cdb.set_company_run(company["id"], job_id, None)
    log.info("company=%s scraped=%d kept=%d", company["name"], len(rows), kept)
