# CLAUDE.md

This file gives Claude Code (and any human reading this repo) full context on
what this project is, how it's structured, and the conventions to follow when
writing code in it. Read this before making changes.

---

## 1. What this project is

A web app where a user submits:

- a **URL**
- a **JSON schema** (the shape of data they want back)
- a **prompt** (plain-English description of what to extract, and how to
  navigate — e.g. "search for 'running shoes' and get the first 20 results
  across all pages")

The system then:

1. Loads the page with a real browser (Playwright) and inspects its structure
2. Asks an LLM (Grok) to **write a Python + Playwright script** that
   performs the navigation/search/pagination described in the prompt and
   extracts data matching the JSON schema
3. Runs that script in a sandboxed subprocess
4. Validates the output against the JSON schema
5. If it fails, feeds the error back to the LLM, gets a fixed script, retries
   (capped)
6. Returns the extracted data + the working script to the user

**In one sentence:** this is a "describe the data you want, get a working
scraper" tool, with an automatic self-healing loop so first-draft LLM code
doesn't have to be perfect.

---

## 2. Why this architecture (read this before "improving" it)

A few decisions are intentional — don't undo them without a good reason:

- **We generate a persistent script, not a live agentic loop.** A live agent
  (LLM decides every click in real time) is more flexible but costs one LLM
  call per navigation step and is slow. A generated script runs once for
  free after it works. We pay the LLM cost once at generation time, then
  reuse/re-run the script cheaply.
- **The self-healing loop is the actual product.** Raw first-shot LLM
  scripts fail constantly on real sites (dynamic class names, lazy-loaded
  content, unexpected popups). The retry-with-error-feedback loop is what
  makes this usable — don't remove it to "simplify."
- **Scripts run in a subprocess, never in-process.** Generated code is
  LLM-written and executes against arbitrary third-party sites. It must be
  sandboxed (subprocess + timeout + resource limits) so a bad or hostile
  script can't take down the backend.
- **No queue/broker for v1.** FastAPI `BackgroundTasks` is enough for one
  job at a time. Don't introduce Redis/Celery/arq until concurrency is an
  actual bottleneck — it adds real operational complexity for no v1 benefit.
- **A successful script is reused, not regenerated.** A job whose URL, prompt
  and schema exactly match an earlier successful one replays that saved script
  (recorded as attempt 0) instead of paying for recon and an LLM call. A
  replay that fails falls through into the normal loop with the failure as
  repair context, so a stale script self-heals rather than dead-ending.
- **Recon happens before generation, not during.** We capture a cleaned-up
  DOM snapshot first and hand it to the LLM as context, instead of letting
  the LLM "explore" the live page itself. This keeps generation to a single
  LLM call in the common case and keeps token usage predictable.

---

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI (Python) | Same language as generated scripts — no cross-language glue, can import/validate directly |
| Browser automation | Playwright (Python) | Handles JS-rendered sites, form filling, clicking — requests/BeautifulSoup can't |
| Script execution | Python subprocess | Isolation from the main server process |
| Database | MySQL | Stores jobs, generated scripts, run history |
| Background jobs | FastAPI `BackgroundTasks` | Simplest thing that works for v1; upgrade to Redis+arq only if needed |
| LLM | xAI API (Grok), plain HTTP via httpx | Writes and repairs the extraction scripts. Anthropic path kept commented in `generate.py` |
| Schema validation | Pydantic | Validates script output against the user's JSON schema |
| Frontend | Vite + React 19, zustand for state | Form for input, polling view for job status/results. zustand's `persist` keeps the draft, the view and the running job across a refresh |

No Docker/Kubernetes/message broker in v1. Add infrastructure only when the
simple version actually breaks under real load — not preemptively.

---

## 4. Folder structure

```
/backend
  main.py              # FastAPI app: routes, request/response models
  models.py             # Pydantic schemas + DB row models
  db.py                 # MySQL connection setup (pymysql)
  recon.py              # Playwright: loads page, extracts cleaned DOM,
                         # detects search boxes / pagination pattern
  generate.py            # Builds the LLM prompt, calls Claude, returns script code
  executor.py            # Runs a script in a subprocess with a timeout,
                         # captures stdout/stderr, validates output
  retry_loop.py           # Orchestrates generate -> execute -> validate ->
                         # (on failure) regenerate, capped at N attempts
/frontend                # Vite + React 19 + zustand. `npm run dev` / `npm run build`
  index.html             # Vite entry
  vite.config.js         # dev server on :5173, build to ./dist
  src/
    main.jsx             # mounts <App/>
    App.jsx              # topbar + which page, and the one job poller
    store.js             # the zustand store: every piece of state, and persist
    api.js               # API base and fetch helpers. No DOM, no React
    schema.js            # builder rows <-> JSON Schema
    style.css            # design.md tokens + components
    pages/               # NewJob, Browse, and the browse tab config
    components/          # Topbar, JobCard, SchemaBuilder, tables, primitives
    hooks/useJobPoll.js  # polls the watched job; reattaches after a refresh
CLAUDE.md                # this file
```

Keep each backend module single-purpose. `recon.py` never calls the LLM.
`generate.py` never touches Playwright directly. `executor.py` never talks to
Claude. This separation is what makes the retry loop in `retry_loop.py`
simple to reason about.

---

## 5. Data flow (detailed)

```
POST /jobs  { url, json_schema, prompt }
        │
        ▼
1. Create a `jobs` row, status = "pending". Return job_id immediately.
        │
        ▼ (background task starts)
2. REUSE CHECK (db.find_cached_script, from retry_loop.py)
   - Look for a prior successful script for this exact url + prompt + schema
   - Hit: run it (attempt 0), and on success the job is done here. No browser,
     no LLM. On failure, keep it as repair context and carry on to step 3
   - Miss: carry on to step 3
        │
        ▼
3. RECON (recon.py)
   - Launch headless Playwright, navigate to `url`
   - Strip the DOM down to: tag, id, class, data-testid, aria-label,
     visible text, href — discard <script>, <style>, <svg>, inline styles
   - Detect interactive elements: search inputs + their submit mechanism
     (Enter key vs. a submit button), "next page" links, numbered
     pagination, or infinite-scroll triggers
   - Output: a compact structured summary, NOT raw HTML
        │
        ▼
4. GENERATE (generate.py) — LLM call #1
   - Input: cleaned DOM summary + json_schema + prompt
   - Ask Claude for a Python script with a FIXED contract:
       def run(page) -> list[dict]
     The harness (executor.py) owns browser launch, retries, and output
     serialization — the generated script only implements extraction logic.
        │
        ▼
5. EXECUTE (executor.py)
   - Run the script in a subprocess, timeout ~60s, resource-limited
   - Capture stdout (the returned list[dict]) and any traceback
        │
        ▼
6. VALIDATE
   - Check output against `json_schema` using Pydantic
   - Empty result, schema mismatch, or exception = failure
        │
        ├─ SUCCESS → save script + result to DB, job status = "done"
        │
        └─ FAILURE → feed {error, traceback, relevant DOM snippet} back to
                      Claude (LLM call #2), get a fixed script, go to step 5.
                      Cap at 3 total attempts. If still failing, job status
                      = "failed", store the last error for the user.
```

Frontend polls `GET /jobs/{id}` until status is `done` or `failed`.

---

## 6. Database schema

```sql
-- mysql -u root < schema.sql
create database if not exists ai_scripts;
use ai_scripts;

create table if not exists jobs (
  id            char(36) primary key,   -- uuid4, generated in db.py
  url           text not null,
  json_schema   json not null,
  prompt        text not null,
  status        varchar(16) not null,   -- pending | running | done | failed
  error         text,
  created_at    timestamp default current_timestamp,
  updated_at    timestamp default current_timestamp on update current_timestamp
);

create table if not exists script_attempts (
  id              char(36) primary key,
  job_id          char(36) not null,
  attempt_number  int not null,   -- 0 = replay of a saved script,
                                  -- 1..3 = generated by the LLM
  script_code     mediumtext not null,
  error_message   text,           -- null if this attempt succeeded
  output_json     json,           -- null if this attempt failed
  success         boolean not null,
  created_at      timestamp default current_timestamp,
  foreign key (job_id) references jobs(id),
  index script_attempts_job_id_idx (job_id)
);
```

`script_attempts` keeps the full history of every attempt per job — useful for
debugging why a script failed, and it *is* the saved-script store: a row with
`success = 1`, joined to its job for the url/prompt/schema, is what the reuse
check reads back. There is deliberately no separate `cached_scripts` table to
keep in sync.

---

## 7. API surface (v1)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/jobs` | Create a job (`url`, `json_schema`, `prompt`). Returns `job_id`. |
| `GET` | `/jobs/{id}` | Poll job status. Returns status, and once done: the result data + the final working script. |
| `GET` | `/jobs/{id}/attempts` | List all attempts for a job. Debugging. |
| `GET` | `/jobs` | List every job, newest first (`limit`, `offset`). |
| `GET` | `/attempts` | List every attempt across all jobs. |
| `GET` | `/scripts` | List saved scripts available for reuse, with `reuse_count`. |

---

## 8. Conventions for Claude Code when working in this repo

- **Never execute generated scripts in-process.** Always via `executor.py`'s
  subprocess runner. This is a hard security boundary, not a style
  preference.
- **Generated scripts must only implement `def run(page) -> list[dict]`.**
  Don't let the LLM prompt drift into asking for full standalone scripts
  (browser launch, imports, etc.) — that logic belongs in the harness so
  validation and sandboxing stay centralized.
- **Recon output must be compact.** If `recon.py` starts passing large
  raw HTML to `generate.py`, that's a bug — it wastes tokens and produces
  worse selectors (LLMs write more reliable code from
  `data-testid`/`aria-label`/`id` than from generated class names).
- **Schema validation lives in the harness, not in generated scripts.**
  Generated scripts return raw dicts; `executor.py` does the Pydantic
  validation. Don't duplicate schema logic inside prompts to the LLM.
- **A replay is attempt 0, a generation is attempt 1-3.** That numbering is
  the cache-hit marker across the whole project (DB, API, both frontend
  pages). Do not renumber it, and do not let a replay spend one of the three
  LLM attempts.
- **Respect the retry cap (3 attempts).** Don't let the loop retry
  indefinitely — surface a clear failure to the user with the last error
  instead.
- **New infra (Redis, queues, Docker) requires a stated reason.** Don't add
  it speculatively; this project intentionally starts minimal per Section 3.

---

## 9. Known limitations (v1, by design)

- One job runs at a time per request (no queue/concurrency yet)
- Script reuse is keyed on exact url + prompt + schema. Nothing reuses across
  a reworded prompt or a sibling page on the same domain
- No cache invalidation or TTL — a saved script is retired only by failing a
  replay
- No auth/rate-limiting on the API yet
- No handling for sites requiring login/auth walls

These are acceptable gaps for v1 and should be treated as backlog, not as
bugs to silently "fix" by adding complexity.