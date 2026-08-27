# Plan 05 — Retry loop

**Goal:** orchestrate recon → generate → execute → validate → repair, capped at
3 attempts, persisting every attempt. This is the product (`CLAUDE.md` §2).

**Owner:** `backend-engineer`.

## Files

```
backend/retry_loop.py
tests/test_retry_loop.py
```

## The flow

```python
def run_job(job_id: uuid.UUID) -> None:
    db.set_status(job_id, "running")
    job = db.get_job(job_id)
    try:
        rec = recon.recon(job["url"])
    except Exception as e:
        db.set_status(job_id, "failed", error=f"recon failed: {e}")
        return

    prior = None
    for n in range(1, MAX_ATTEMPTS + 1):          # MAX_ATTEMPTS = 3
        code = generate.generate(rec, job["json_schema"], job["prompt"], prior)
        att = executor.execute(code, job["url"], job["json_schema"])
        db.add_attempt(job_id, n, att.code, att.error, att.output, att.success)
        if att.success:
            db.set_status(job_id, "done")
            return
        prior = att

    db.set_status(job_id, "failed", error=prior.error)
```

## Rules this stage must hold

- **Recon runs once**, before the loop. Re-running it per attempt triples the
  browser cost for a page that has not changed.
- **The attempt row is written before the next attempt starts.** If the process
  dies mid-loop, the history is still there.
- **Cap at 3.** Not configurable upward (`rules.md` §C14). The user gets the
  last error verbatim, not a vague failure.
- **Nothing here imports `anthropic`, `playwright`, or `subprocess` directly**
  (`rules.md` §B6). It calls the three modules and nothing else.
- Wrap the whole body so an unexpected exception still lands the job in
  `failed` with a message — a job stuck in `running` forever is the worst
  outcome for the frontend.

## Check (`test-engineer`)

Stub `recon`, `generate`, `executor` — no browser, no API (`rules.md` §E22-23).

- **Happy path:** first attempt succeeds → status `done`, exactly 1 attempt row.
- **Repair path:** attempts 1 and 2 fail, 3 succeeds → status `done`, 3 rows,
  and assert `generate` received the *previous* attempt's error on calls 2 and 3.
  This is the one behaviour that makes the product work; test it explicitly.
- **Exhaustion:** all 3 fail → status `failed`, 3 rows, `jobs.error` equals the
  third attempt's error.
- **Recon failure:** recon raises → status `failed`, 0 attempt rows, `generate`
  never called.
- **Recon called once:** across a 3-attempt run, `recon` call count == 1.
- **Unexpected crash:** `generate` raises `RuntimeError` → status `failed`, not
  stuck in `running`.

## Out of scope

Resuming a partially-run job, cross-job script reuse, adaptive attempt counts.
