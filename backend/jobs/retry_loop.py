"""The self-healing loop: recon -> generate -> execute -> validate -> repair.

The only module that knows the order of operations (architecture.md 2). It
calls recon, generate and executor and imports nothing they own -- no
anthropic, no playwright, no subprocess (rules.md B6).
"""
import logging
import uuid
from typing import Callable

from backend.jobs import db
from backend.llm import generate
from backend.scraping import executor, recon
from backend.config import MAX_ATTEMPTS
from backend.contracts import Attempt

log = logging.getLogger(__name__)

# A rail over one extracted row: the reason it is wrong, or None. Named here
# because it crosses three function signatures below.
RowCheck = Callable[[dict], str | None] | None


def run_job(job_id: uuid.UUID, script: str | None = None,
            row_check: RowCheck = None) -> None:
    """Drive one job to `done` or `failed`. Never raises: a job stuck in
    `running` is the worst outcome for the frontend poller (rules.md F26).

    `script` is a caller-supplied `def run(page)` -- see _run_supplied.

    `row_check` is passed straight through to every execute() in here, so a
    caller that knows what its rows mean gets the repair loop working on truth
    and not only on shape. It is threaded rather than looked up because this
    module orchestrates; deciding what a good row is belongs to whoever asked
    for the job.
    """
    try:
        _drive(job_id, script, row_check)
    except Exception as e:
        db.set_status(job_id, "failed", error=f"{type(e).__name__}: {e}")


def _replay(job_id: uuid.UUID, job: dict, row_check: RowCheck = None) -> Attempt | None:
    """Run the script this exact job already produced once before, if there is
    one, and record it as attempt 0.

    Attempt 0 is the cache-hit marker everywhere in this project. It costs no
    recon and no LLM call, so it does not spend one of the three attempts
    rules.md C14 caps -- those stay 1..MAX_ATTEMPTS.

    Returns None when nothing was cached.
    """
    code = db.find_cached_script(job["url"], job["json_schema"], job["prompt"])
    if code is None:
        return None

    att = executor.execute(code, job["url"], job["json_schema"], row_check=row_check)
    db.add_attempt(job_id, 0, att.code, att.error, att.output, att.success)
    return att


def _run_supplied(job_id: uuid.UUID, job: dict, code: str,
                  row_check: RowCheck = None) -> None:
    """Run a script the user handed us, and stop there.

    Attempt 0, like a replay: no recon, no LLM call, none of the three attempts
    spent. It does not fall through to the repair loop the way a stale cached
    script does -- someone who pasted a script asked to run *that* script, and
    having a model quietly rewrite it costs them money for an answer to a
    question they did not ask.

    Safety is not special-cased here: executor.execute() is the only thing that
    ever runs a script, and its guardrail rail (an `ast` walk) and its sandbox
    (subprocess, timeout, rlimit) sit above this and every other caller.
    """
    att = executor.execute(code, job["url"], job["json_schema"], row_check=row_check)
    db.add_attempt(job_id, 0, att.code, att.error, att.output, att.success)
    if att.success:
        db.set_status(job_id, "done")
    else:
        db.set_status(job_id, "failed", error=att.error)
    log.info("job=%s outcome=%s via=supplied", job_id, "done" if att.success else "failed")


def _drive(job_id: uuid.UUID, script: str | None = None,
           row_check: RowCheck = None) -> None:
    db.set_status(job_id, "running")
    job = db.get_job(job_id)
    if job is None:
        raise LookupError(f"job {job_id} not found")

    if script is not None:
        return _run_supplied(job_id, job, script, row_check)

    prior = _replay(job_id, job, row_check)
    if prior is not None:
        if prior.success:
            db.set_status(job_id, "done")
            log.info("job=%s outcome=done via=cache", job_id)
            return
        # Stale selectors, changed page. The failed replay becomes the repair
        # context for attempt 1 instead of a dead end.
        log.info("job=%s cached script failed, regenerating", job_id)

    # Only now: a cache hit skips the browser launch entirely. Once, not per
    # attempt -- the page does not change between attempts and a launch each
    # time would triple the cost of a repair.
    try:
        rec = recon.recon(job["url"])
    except Exception as e:
        db.set_status(job_id, "failed", error=f"recon failed for {job['url']}: {e}")
        return

    for n in range(1, MAX_ATTEMPTS + 1):
        code = generate.generate(rec, job["json_schema"], job["prompt"], prior)
        att = executor.execute(code, job["url"], job["json_schema"],
                               row_check=row_check)
        # Written before the next attempt starts -- if the process dies
        # mid-loop the audit trail survives (rules.md F25).
        db.add_attempt(job_id, n, att.code, att.error, att.output, att.success)
        if att.success:
            db.set_status(job_id, "done")
            log.info("job=%s outcome=done attempts=%d", job_id, n)
            return
        prior = att

    db.set_status(job_id, "failed", error=prior.error)
    log.info("job=%s outcome=failed attempts=%d", job_id, MAX_ATTEMPTS)
