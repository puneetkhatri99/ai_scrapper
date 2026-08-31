# architecture.md

Authoritative description of how the system is put together. `CLAUDE.md` says
*what* and *why*; this file says *where each thing lives and what may call what*.

---

## 1. Shape

Synchronous HTTP in, background work behind it. One process. No broker.

```
browser ──POST /jobs──▶ FastAPI (main.py) ──▶ MySQL (jobs row, status=pending)
                             │
                             └─ BackgroundTasks ──▶ retry_loop.run(job_id)
                                                        │
                          ┌─────────────────────────────┼─────────────────────────┐
                          ▼                             ▼                         ▼
                    recon.py                     generate.py                executor.py
              (Playwright, no LLM)         (Gemini HTTP call, no browser)  (subprocess, no LLM)

browser ──GET /jobs/{id}──▶ FastAPI ──▶ MySQL (status / result / final script)
```

## 2. Module boundaries (hard)

| Module | May import | May NOT touch | Owns |
|---|---|---|---|
| `config.py` | stdlib | everything else | Env settings and every hard limit |
| `main.py` | models, db, retry_loop | playwright, httpx-to-the-LLM, subprocess, pymysql | HTTP surface, request validation, background dispatch, serving `frontend/dist` |
| `models.py` | pydantic, config | every other project module | Request/response models, DB row models, dynamic schema builder |
| `db.py` | pymysql, config | business logic | Connection handling, `jobs` + `script_attempts` CRUD, the saved-script lookup |
| `recon.py` | playwright, config | the LLM call, db | Page load, DOM reduction, interaction detection |
| `generate.py` | httpx, models, prompts, config | playwright, subprocess, db | Prompt assembly, LLM call, code extraction |
| `executor.py` | subprocess, playwright(harness only), models, config | the LLM call, db | Sandboxed run, stdout capture, schema validation |
| `retry_loop.py` | recon, generate, executor, db, config | the LLM call, playwright, subprocess (directly) | Orchestration + attempt bookkeeping, the replay-before-recon decision |

`config.py` is a stdlib-only leaf, so importing it can never create a cycle or
smuggle a forbidden dependency in sideways — anything may import it.

`main.py` answers 503 on a dead database by catching `db.Unavailable`, which
`db.py` re-exports for exactly that reason: the HTTP layer never imports
pymysql.

A violation of this table is a bug, not a style choice. `retry_loop.py` is the
only module allowed to know the order of operations. `tests/test_hardening.py`
enforces the "may NOT touch" column with an AST walk — the table is executable,
not aspirational.

## 3. Contracts between modules

These four types are the whole interface surface. Change them deliberately.

```python
# recon.py
@dataclass
class Recon:
    url: str
    title: str
    elements: list[dict]      # {tag, id, class, testid, aria, text, href} — trimmed
    search: dict | None       # {selector, submit: "enter" | "<button selector>"}
    pagination: dict | None   # {kind: "next_link"|"numbered"|"infinite_scroll", selector}

# generate.py
def generate(recon: Recon, json_schema: dict, prompt: str,
             prior: Attempt | None = None) -> str: ...   # returns script source

# models.py -- not executor.py: generate.py needs the type but may not
# import executor.py (2 above), and models.py imports nothing else.
@dataclass
class Attempt:
    code: str
    output: list[dict] | None
    error: str | None         # traceback or validation message
    success: bool

# executor.py
def execute(code: str, url: str, json_schema: dict, timeout: int = 60) -> Attempt: ...
```

## 4. The generated-script contract

The LLM writes exactly one function. Nothing else.

```python
def run(page) -> list[dict]:
    ...
```

The harness (`executor.py`) owns: browser launch, `page.goto(url)`, timeout,
JSON serialization to stdout, and Pydantic validation. The generated script
owns: navigation actions, waiting, and extraction. It never launches a browser,
never validates, never prints.

Why: sandboxing and validation stay in one place, and the LLM has a smaller,
more reliable job.

## 5. Execution sandbox

`executor.py` writes the harness + generated `run()` to a temp file and runs it
as `subprocess.run([sys.executable, path], capture_output=True, timeout=N)`.

- Hard wall-clock timeout (default 60s), `kill()` on expiry
- `resource.setrlimit(RLIMIT_AS, ...)` inside the harness, after the browser
  launches — a child inherits the limit at spawn time and chromium reserves
  far more address space than the cap, so setting it earlier (or in a
  `preexec_fn`) would stop chromium from starting. Best effort: Darwin
  rejects `RLIMIT_AS` outright, so a mac dev box is bounded by the timeout only.
- stdout is parsed as JSON; stderr is captured verbatim as the error feedback
- Never `exec()`, never `import` the generated module in-process

## 6. LLM layer (`generate.py`)

Google Gemini over plain HTTP: `POST
https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`,
Google's OpenAI-compatible surface. No provider SDK.

- **Two models, split by job:** `GEMINI_MODEL` (default `gemini-3.7-flash`)
  writes the first script from recon; `GEMINI_REPAIR_MODEL` (default
  `gemini-3.1-flash-lite`) rewrites it from a traceback on attempts 2..3. The
  branch is one line in `generate()` — `prior is not None` already marks a
  repair. Both env-driven, so switching models is not a code change.
- **Credentials:** `GEMINI_API_KEY` or `GOOGLE_API_KEY`, read inside
  `generate()` at call time. Never a module global, never logged (rules.md A3).
- **Step down, don't back off.** A 503 (Gemini shedding load) or 429 (per-model
  quota) on the writer retries once on `GEMINI_REPAIR_MODEL` — a worse script
  beats a failed job. Any other non-2xx, and a 503 on the repair model itself,
  fails immediately. That is the only retry in here: no SDK, no streaming, no
  backoff, one `httpx` POST per model with a `LLM_TIMEOUT` read timeout.
- **Errors keep their body.** Gemini puts the reason (unknown model, a
  free-tier quota of 0 on Pro, bad key) in the response body, so a non-2xx raises `httpx.HTTPStatusError`
  with that body in the message.
- **Caching:** the system message (script contract + rules) is frozen and sent
  first, byte-identical every call. Volatile content — recon summary, user
  schema, user prompt, prior error — follows it. xAI caches the prefix
  automatically; verify with `usage.prompt_tokens_details.cached_tokens`, and a
  zero across repeat calls means something volatile leaked into the prefix.
- **The Anthropic path is kept commented in `generate.py`.** Prompt assembly
  and code extraction are shared, so switching back is two edits, not a
  rewrite.

## 7. Retry loop

```
recon ──▶ generate ──▶ execute ──▶ validate
                ▲                     │
                └── error feedback ◀───┘   (max 3 total attempts)
```

Every attempt — success or failure — is written to `script_attempts` before the
next one starts. If attempt 3 fails, the job is `failed` and the last error is
surfaced verbatim to the user. No fourth attempt, no exponential wandering.

## 8. Persistence

Schema is in `CLAUDE.md` §6. Two rules:

- `jobs.status` is the single source of truth the frontend polls.
- `script_attempts` is append-only. Never update a row to "fix" history — the
  point of the table is the audit trail of what the LLM actually produced.
- **A restart abandons any in-flight job.** `BackgroundTasks` lives in the
  server process; nothing resumes a half-run job. On startup, `main.py` sweeps
  `running` rows older than `STALE_RUNNING_MIN` into `failed` so the frontend
  never polls a job that no longer has an owner. Re-running the job is the
  user's call, not an automatic retry.

## 9. Frontend

Vite + React 19 + zustand, in `frontend/`. `npm run dev` serves :5173 with hot
reload and talks to the API on :8000 cross-origin (that origin is in
`main.py`'s `ORIGINS` for exactly this). `npm run build` emits `frontend/dist`,
which `main.py` mounts after every route -- same origin, no CORS.

```
main.jsx ─▶ App.jsx ─┬─ Topbar          page ∈ {new, browse}, from the store
                     ├─ pages/NewJob    UrlField · SchemaField · PromptField · JobCard
                     ├─ pages/Browse    Tabs · BrowseTable · details
                     └─ useJobPoll()    mounted here, so polling survives a page switch
                              │
                          store.js  ── zustand + persist(localStorage)
```

**One store, four slices** (`src/store.js`): the shell, the new-job draft, the
watched job, and the browse tables. Zustand rather than Redux Toolkit because
`persist` is the refresh requirement in eight lines; RTK plus redux-persist is
roughly three times the bundle for the same behaviour. Components subscribe to
single fields (`useStore((s) => s.draft.url)`), so a keystroke in the prompt
box re-renders the prompt box and nothing else. `selectBusy` and
`selectAttemptLine` are derived at subscribe time, never stored.

Flow is unchanged: form → POST /jobs → poll `GET /jobs/{id}` every 2s, giving
up after 5 minutes → render result table + the working script.

**State survives a refresh.** `persist`'s `partialize` names exactly what is
kept: draft, page, browse tab, open rows, and `jobId`. Fetched rows and the
polled `job` are deliberately excluded -- a cache that outlived the page would
show stale jobs. Keeping `jobId` instead is what lets `useJobPoll` reattach to
a job that is still running.

No router: `page` is a store key. Rows in `BrowseTable` are `memo`ised and read
their own open flag from the store, so expanding one row of two hundred
re-renders one row.

Tests are `node:test` on bare node -- `tests/schema.test.mjs` for the schema
translation, `tests/store.test.mjs` for the store, both via `npm test` in
`frontend/`. No jsdom, no test renderer. See `design.md` for the visual system.

## 10. What is deliberately absent

Redis, Celery, Docker, auth, rate limiting, script caching, concurrency. Each
is listed in `CLAUDE.md` §9 as backlog. Adding any of them requires a written
reason in the PR, per `rules.md`.
