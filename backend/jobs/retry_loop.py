"""The self-healing loop: recon -> generate -> execute -> validate -> repair.

The only module that knows the order of operations (architecture.md 2). It
calls recon, generate and executor and imports nothing they own -- no
anthropic, no playwright, no subprocess (rules.md B6).
"""
import logging
import uuid
from typing import Callable

from backend import tracing
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
    # The outermost span is the trace: every step below nests under it, so
    # "what did this job do, for how many tokens, and why did it stop" is one
    # page in Langfuse rather than a log grep. Off unless the keys are set.
    try:
        with tracing.span("job", input={"job_id": str(job_id)}):
            try:
                _drive(job_id, script, row_check)
            except Exception as e:
                _end(job_id, "failed", f"{type(e).__name__}: {e}")
    finally:
        # Outside the span, not inside it: a flush that runs before the job
        # span closes sends the children and leaves the trace headless until
        # some later job happens to flush again. And a BackgroundTask has
        # nobody waiting on it to do this at all.
        tracing.flush()


def _end(job_id: uuid.UUID, status: str, error: str | None = None) -> None:
    """Finish the job: the row, and the trace, together.

    Every path out of this loop goes through here, so the trace carries the
    outcome without four call sites each remembering to say so.
    """
    db.set_status(job_id, status, error=error)
    tracing.update(
        output={"status": status, "error": error},
        level="ERROR" if status == "failed" else None,
        status_message=error,
    )


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

    with tracing.span("replay saved script") as sp:
        att = executor.execute(code, job["url"], job["json_schema"], row_check=row_check)
        sp.update(output={"success": att.success, "error": att.error})
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
    with tracing.span("supplied script") as sp:
        att = executor.execute(code, job["url"], job["json_schema"], row_check=row_check)
        sp.update(output={"success": att.success, "error": att.error})
    db.add_attempt(job_id, 0, att.code, att.error, att.output, att.success)
    _end(job_id, "done" if att.success else "failed", None if att.success else att.error)
    log.info("job=%s outcome=%s via=supplied", job_id, "done" if att.success else "failed")


def _drive(job_id: uuid.UUID, script: str | None = None,
           row_check: RowCheck = None) -> None:
    db.set_status(job_id, "running")
    job = db.get_job(job_id)
    if job is None:
        raise LookupError(f"job {job_id} not found")

    # The trace is worth nothing if you cannot tell which job it is.
    tracing.update(input={"url": job["url"], "prompt": job["prompt"]})

    if script is not None:
        return _run_supplied(job_id, job, script, row_check)

    prior = _replay(job_id, job, row_check)
    if prior is not None:
        if prior.success:
            _end(job_id, "done")
            log.info("job=%s outcome=done via=cache", job_id)
            return
        # Stale selectors, changed page. The failed replay becomes the repair
        # context for attempt 1 instead of a dead end.
        log.info("job=%s cached script failed, regenerating", job_id)

    # Only now: a cache hit skips the browser launch entirely. Once, not per
    # attempt -- the page does not change between attempts and a launch each
    # time would triple the cost of a repair.
    try:
        with tracing.span("recon", input=job["url"]):
            rec = recon.recon(job["url"])
    except Exception as e:
        _end(job_id, "failed", f"recon failed for {job['url']}: {e}")
        return

    for n in range(1, MAX_ATTEMPTS + 1):
        # One span per attempt, so "it took three tries and here is what the
        # third one still got wrong" is the shape of the trace, not a note in it.
        with tracing.span(f"attempt {n}") as sp:
            code = generate.generate(rec, job["json_schema"], job["prompt"], prior)
            att = executor.execute(code, job["url"], job["json_schema"],
                                   row_check=row_check)
            sp.update(output={"success": att.success, "error": att.error,
                              "rows": len(att.output or [])})
        # Written before the next attempt starts -- if the process dies
        # mid-loop the audit trail survives (rules.md F25).
        db.add_attempt(job_id, n, att.code, att.error, att.output, att.success)
        if att.success:
            _end(job_id, "done")
            log.info("job=%s outcome=done attempts=%d", job_id, n)
            return
        prior = att

    _end(job_id, "failed", prior.error)
    log.info("job=%s outcome=failed attempts=%d", job_id, MAX_ATTEMPTS)
