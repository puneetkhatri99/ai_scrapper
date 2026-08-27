# Plan 06 — API

**Goal:** the three routes from `CLAUDE.md` §7, wired to the retry loop via
`BackgroundTasks`. No broker (`rules.md` §D18).

**Owner:** `backend-engineer`.

## Files

```
backend/main.py
tests/test_api.py
```

## Routes

| Method | Path | Returns |
|---|---|---|
| `POST` | `/jobs` | `{job_id}` — 202, immediately |
| `GET` | `/jobs/{id}` | status; plus `result` + `script` when `done`, `error` when `failed` |
| `GET` | `/jobs/{id}/attempts` | full attempt history (debugging) |
| `GET` | `/health` | `{"ok": true}` |

## Steps

1. **`POST /jobs`** — validate with `JobCreate` (`models.py` does the real
   validation; the route just accepts the model). Insert the row with
   `status="pending"`, then
   `background_tasks.add_task(retry_loop.run_job, job_id)`. Return `job_id`
   **before** any work starts — that is the whole point of the async shape.
2. **`GET /jobs/{id}`** — 404 on unknown id. Build the response from the job row
   plus its attempts:
   - `attempts`: count so far (the frontend shows "attempt N / 3")
   - `result` / `script`: from the successful attempt, when `status == "done"`
   - `error`: `jobs.error`, when `status == "failed"`
3. **`GET /jobs/{id}/attempts`** — the raw list. Useful when a job fails and you
   need to see what the LLM actually wrote.
4. **CORS** — allow the local frontend origin only. Not `*`.
5. **Nothing in `main.py` imports playwright, anthropic, or subprocess**
   (`rules.md` §B6).

## Check (`test-engineer`)

`fastapi.testclient.TestClient`, with `retry_loop.run_job` stubbed for the fast
tests.

- `POST /jobs` with a valid body → 202 + a uuid; the row exists with
  `status="pending"`; the background task was scheduled.
- `POST /jobs` with `ftp://…`, an empty prompt, a non-dict schema → 422 each.
- `GET /jobs/{unknown}` → 404.
- Status transitions render correctly: seed `pending` / `running` / `done` /
  `failed` rows and assert the response shape for each — `result` and `script`
  present only on `done`, `error` present only on `failed`.
- **One real end-to-end test**, run against the local fixture page with a
  stubbed `generate` that returns a hand-written correct `run()`:
  `POST /jobs` → poll → `done` → the result rows match the fixture. Real
  Playwright, real subprocess, no API call. This is the test that proves the
  pipeline is actually connected.

## Out of scope

Auth, rate limiting, pagination of the jobs list, websockets. Polling is fine.
