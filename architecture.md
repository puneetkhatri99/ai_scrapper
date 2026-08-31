# architecture.md

Authoritative description of how the system is put together. `CLAUDE.md` says
*what* and *why*; this file says *where each thing lives and what may call what*.

---

## 1. Shape

Synchronous HTTP in, background work behind it. One process. No broker.

```
browser ──POST /jobs──▶ jobs/router.py ──▶ MySQL (jobs row, status=pending)
                             │
                             └─ BackgroundTasks ──▶ jobs/retry_loop.run_job(job_id)
                                                        │
                          ┌─────────────────────────────┼─────────────────────────┐
                          ▼                             ▼                         ▼
                 scraping/recon.py            llm/generate.py          scraping/executor.py
              (Playwright, no LLM)      (Gemini HTTP call, no browser)  (subprocess, no LLM)

browser ──GET /jobs/{id}──▶ jobs/router.py ──▶ MySQL (status / result / final script)

browser ──POST /companies/run──▶ companies/router.py ──▶ BackgroundTasks
                                                             │
                                        companies/runner.py ─┴─ per company:
                                          jobs/retry_loop.run_job(id, script=saved)
                                          then upsert into loan_officers
```

The batch adds no execution path of its own. `run_job(id)` is the ordinary
loop and may reach the model; `run_job(id, script=saved)` is the
supplied-script path and cannot. Those two calls are the whole difference
between the Generate scripts button and the Run all button.

## 2. Module boundaries (hard)

The package is grouped by feature, not by layer. Each feature owns its whole
vertical slice, and the two shared leaves sit outside all of them:

```
backend/
  main.py           app assembly only: middleware, 503 handler, routers, static
  config.py         env settings + every hard limit          (stdlib-only leaf)
  contracts.py      Attempt -- the one type crossing features (imports nothing)
  guardrails.py     the three rails: the url, the script, the scraped row
  mysql.py          the connection, shared by both db.py modules      (leaf)
  jobs/             a scrape request's life: router, schemas, db, retry_loop
  scraping/         the browser: recon, executor, harness.py.tmpl
  llm/              the model: generate, prompts
  companies/        the broker list and the officers scraped off it
  evals/            is the data right? in the package, not part of the app
```

| Module | May import | May NOT touch | Owns |
|---|---|---|---|
| `config.py` | stdlib | everything else | Env settings and every hard limit |
| `contracts.py` | dataclasses | every project module | `Attempt`, the one type three features share |
| `guardrails.py` | stdlib, config | every other project module | The URL rail, the script rail, the officer-row rail |
| `main.py` | jobs.db, jobs.router | playwright, httpx-to-the-LLM, subprocess, pymysql | App assembly, CORS, the 503 handler, serving `frontend/dist` |
| `jobs/router.py` | jobs.db, jobs.schemas, jobs.retry_loop | playwright, httpx-to-the-LLM, subprocess, pymysql | HTTP surface, background dispatch |
| `jobs/schemas.py` | pydantic, config, guardrails | every other project module | Request/response models, boundary validation |
| `jobs/db.py` | pymysql, config | business logic | Connection handling, `jobs` + `script_attempts` CRUD, the saved-script lookup |
| `jobs/retry_loop.py` | scraping, llm, jobs.db, contracts, config | the LLM call, playwright, subprocess (directly) | Orchestration + attempt bookkeeping, the replay-before-recon decision |
| `scraping/recon.py` | playwright, config | the LLM call, db | Page load, DOM reduction, interaction detection, following one card |
| `scraping/executor.py` | subprocess, contracts, config, guardrails | the LLM call, db | Sandboxed run, script rail, stdout capture, schema validation |
| `llm/generate.py` | httpx, contracts, llm.prompts, config | playwright, subprocess, db | Prompt assembly, LLM call, code extraction |
| `llm/prompts.py` | nothing | everything | The frozen system prompt |
| `mysql.py` | pymysql, config | every other project module | The connection, and `Unavailable` |
| `companies/router.py` | companies.{db,schemas,runner} | playwright, httpx-to-the-LLM, subprocess, pymysql | HTTP surface, the batch dispatch, the 409 |
| `companies/schemas.py` | pydantic, config, guardrails | every other project module | `CompanyIn`, boundary validation |
| `companies/db.py` | mysql, config | business logic | `companies` + `loan_officers`, the officer upsert |
| `companies/runner.py` | companies.db, jobs.{db,retry_loop} | playwright, subprocess, the LLM call | Batch order, `OFFICER_SCHEMA`/`OFFICER_PROMPT`, harvesting |
| `companies/seed.py` | csv, companies.db | everything else | The one-time CSV import |
| `evals/cases.py` | dataclasses, guardrails, companies.runner | playwright, httpx, subprocess, **any db** | The corpus: page, prompt, schema, correct rows |
| `evals/run.py` | config, evals.cases, llm, scraping | playwright, httpx, subprocess, **any db**, **jobs.retry_loop** | Serving the fixtures, driving the loop, scoring |

`config.py` and `contracts.py` are leaves, so importing either can never create
a cycle or smuggle a forbidden dependency in sideways — anything may import them.
`guardrails.py` is a leaf too (stdlib plus `config`), which is what lets every
trust boundary call the same rails: the HTTP one in `jobs/schemas.py`, the
execution one in `scraping/executor.py`, and the storage one in
`companies/db.py`.

The evals sit inside the package but outside the app -- nothing imports them at
runtime. Two rows of the table above are the reason it was worth moving them
in: an eval may not name a database, and may not import `jobs/retry_loop.py`.
Both guard the same mistake. The real loop replays a saved script when the url,
prompt and schema match, and an eval that did that would score the cache rather
than the model -- silently, and in the flattering direction.

Features do not import each other's internals sideways: `llm` never imports
`scraping` at runtime (`generate.py` type-hints `Recon` under `TYPE_CHECKING`
only), and only `jobs/retry_loop.py` imports both.

`companies` is the one feature built on another, and the dependency runs one
way only: `companies/runner.py` calls `jobs.retry_loop` and `jobs.db`, and
nothing in `jobs` knows companies exist. `jobs/retry_loop.py` is still the only
module that knows the order of operations *within* a job; `companies/runner.py`
knows the order of the batch, which is a different question.

`main.py` answers 503 on a dead database by catching `db.Unavailable`, which
`jobs/db.py` re-exports for exactly that reason: the HTTP layer never imports
pymysql.

A violation of this table is a bug, not a style choice. `jobs/retry_loop.py` is
the only module allowed to know the order of operations.
`tests/test_hardening.py` enforces the "may NOT touch" column with an AST walk,
and fails if a new module is added without a row — the table is executable, not
aspirational.

## 3. Contracts between modules

These four types are the whole interface surface. Change them deliberately.

```python
# scraping/recon.py
@dataclass
class Recon:
    url: str
    title: str
    elements: list[dict]      # {tag, id, class, testid, aria, text, href} — trimmed
    search: dict | None       # {selector, submit: "enter" | "<button selector>"}
    pagination: dict | None   # {kind: "next_link"|"numbered"|"infinite_scroll", selector}

# llm/generate.py
def generate(recon: Recon, json_schema: dict, prompt: str,
             prior: Attempt | None = None) -> str: ...   # returns script source

# contracts.py -- not scraping/executor.py: llm/generate.py needs the type but
# may not import it (2 above), and contracts.py imports nothing at all.
@dataclass
class Attempt:
    code: str
    output: list[dict] | None
    error: str | None         # traceback or validation message
    success: bool

# scraping/executor.py
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

## 6. The three rails (`guardrails.py`)

Three artifacts in this system are written by someone outside the repo, and
each gets a deterministic rail. No rail is a model judging another model: that
would cost an LLM call per job to answer a question a parser answers exactly.

| Rail | Artifact | Called from | On failure |
|---|---|---|---|
| `check_url` | the URL a user submits | `jobs/schemas.py`, `companies/schemas.py` | 422 at the boundary |
| `check_script` | the Python the model wrote | `scraping/executor.py` | a failed attempt the repair loop fixes |
| `check_officer` | the rows that script scraped | `companies/db.py` | the row is dropped; an empty harvest marks the company for regeneration |

The first two are about **safety** -- what the code can reach. The third is
about **truth**, and it exists because safety checks do not catch it: a
perfectly harmless script can return `{"name": "Load More"}` or an NMLS id with
two licence numbers run together, and schema validation waves both through,
because they are strings and the schema asked for strings.

Each rail is called at the single place its artifact crosses into the system,
not at each caller (rules.md H32). `check_script` lives in `executor.execute`
so a *replayed* script is checked too; `check_officer` lives in
`db.upsert_officers` so nothing reaches `loan_officers` any other way.

Every rail ships both halves of its corpus in `tests/test_guardrails.py` --
`ALLOWED`/`BLOCKED`, `KEEP`/`DROP`. A rail with only the blocking half is one
false positive away from burning every attempt on a job.

## 7. LLM layer (`llm/generate.py`)

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

## 8. Retry loop

```
recon ──▶ generate ──▶ execute ──▶ validate
                ▲                     │
                └── error feedback ◀───┘   (max 3 total attempts)
```

`POST /jobs` with a `script` short-circuits all of it: `_run_supplied` executes
that code as attempt 0 and the job ends there, done or failed. No recon, no
model, no repair -- and no special case for safety, because `executor.execute`
is the only thing that ever runs a script and the guardrail rail lives at the
top of it.

Every attempt — success or failure — is written to `script_attempts` before the
next one starts. If attempt 3 fails, the job is `failed` and the last error is
surfaced verbatim to the user. No fourth attempt, no exponential wandering.

## 9. Persistence

Schema is in `CLAUDE.md` §6. Two rules:

- `jobs.status` is the single source of truth the frontend polls.
- `script_attempts` is append-only. Never update a row to "fix" history — the
  point of the table is the audit trail of what the LLM actually produced.
- **A restart abandons any in-flight job.** `BackgroundTasks` lives in the
  server process; nothing resumes a half-run job. On startup, `main.py` sweeps
  `running` rows older than `STALE_RUNNING_MIN` into `failed` so the frontend
  never polls a job that no longer has an owner. Re-running the job is the
  user's call, not an automatic retry.

## 10. Frontend

Vite + React 19 + zustand + Tailwind v4, in `frontend/`. `npm run dev` serves
:5173 with hot reload and talks to the API on :8000 cross-origin (that origin
is in `main.py`'s `ORIGINS` for exactly this). `npm run build` emits
`frontend/dist`, which `main.py` mounts after every route -- same origin, no
CORS.

```
main.jsx ─▶ App.jsx ─┬─ Topbar           page ∈ {new, companies, browse}, from the store
                     ├─ pages/NewJob     UrlField · SchemaField · PromptField · JobCard
                     ├─ pages/Companies  the broker list, edited in place, + the two buttons
                     ├─ pages/Browse     Tabs · BrowseTable · details
                     ├─ Footer           the one link out: /docs.html
                     └─ useJobPoll()     mounted here, so polling survives a page switch
                              │
                          store.js  ── zustand + persist(localStorage)
```

**Styling is Tailwind, and the theme is not `dark:`.** `src/style.css` is the
only CSS file and holds no components: `@import "tailwindcss"`, the design
tokens in `@theme`, and a `:root[data-theme="dark"]` block that redefines the
`--color-*` values. Because a utility compiles to `var(--color-surface)`, that
one block re-themes every element in the app, and no component carries two
class names for two themes -- `main.jsx` stamping `data-theme` on `<html>` is
still the whole of the switch. `src/ui.js` holds the class strings a repeated
control would otherwise spell out per call site (`INPUT`, `GHOST`, `TH`,
`NAME_INPUT`); it is plain text and imports nothing, so the Tailwind scanner
still finds every class in it.

**One store, four slices** (`src/store.js`): the shell, the new-job draft, the
watched job, and the browse tables. Zustand rather than Redux Toolkit because
`persist` is the refresh requirement in eight lines; RTK plus redux-persist is
roughly three times the bundle for the same behaviour. Components subscribe to
single fields (`useStore((s) => s.draft.url)`), so a keystroke in the prompt
box re-renders the prompt box and nothing else. `selectBusy` and
`selectAttemptLine` are derived at subscribe time, never stored.

Flow is unchanged: form → POST /jobs → poll `GET /jobs/{id}` every 2s, giving
up after 5 minutes → render result table + the working script.

**A job is named, not edited.** `PATCH /jobs/{id}` moves one column. The
other three -- url, prompt, schema -- are the reuse key `find_cached_script`
matches on, so editing one in place would leave a saved script attached to a
job it was never generated for. Wanting different inputs means a new job, which
is the same POST as below. The rename deliberately does not touch `updated_at`:
that is the clock `fail_stale_running` measures a `running` job against.

**Re-running is a POST, not a new endpoint.** `runAgain` loads a job's three
inputs back into the draft and submits them; identical inputs are what the
reuse check keys on, so the backend replays the saved script as attempt 0 with
no recon and no LLM call. `GET /jobs/{id}` echoes those three inputs back for
exactly this, which is what makes the button work after a refresh, when the
form no longer holds them.

**State survives a refresh.** `persist`'s `partialize` names exactly what is
kept: draft, page, theme, browse tab, open rows, and `jobId`. Fetched rows and the
polled `job` are deliberately excluded -- a cache that outlived the page would
show stale jobs. Keeping `jobId` instead is what lets `useJobPoll` reattach to
a job that is still running.

**Two buttons, because they cost different things.** Generate scripts is the
only control in the app that can spend money on the broker list; Run all
replays what it wrote. A company with no saved script is skipped by Run all
rather than generated for, so pressing it has a predictable cost of nothing.
`GET /companies/run` reports `running` as the runner's lock itself rather than
a flag beside it, and the lock is taken in the router -- `BackgroundTasks` does
not start until the response has been sent, and a poller arriving in that
window would otherwise decide the batch had already finished.

**One delete, and one add, both at the top.** A row carries no `×`: deleting
one company is ticking one box, which is the same code path as ticking forty,
so there is a single confirm and a single request shape to keep honest.
Adding is a dialog off the head rather than a blank last row -- the table's
cells save on blur, and a half-filled row that saves nothing until you press
Add was the one place on the page where that was not true.

**Selection narrows the batch; it does not add a third path.** Ticking rows
sends the same two POSTs with an `ids` list, which both endpoints already took
-- so "run these three" and "run all" are one call with an argument, and there
is no second route that could drift from the first. The selection itself is
component state, not store state: it is meaningless after a refresh, and the
count is derived by intersecting it with the rows on screen, so a company
deleted under it drops out of the count without anything having to prune a set.
All three bulk actions confirm in a native `<dialog>` -- `showModal()` brings
the backdrop, the focus trap and Escape-to-close, so the modal is markup rather
than a library. Each one's copy says what that action actually does: warning
about credits on Run as well as Generate would teach the user to click through
the warning that matters.

**The scraped officers are a Browse tab, not an editable table.** The next run
merges over them, so an edit there would vanish without saying so.

**The manual is a static file, not a React page.** `frontend/public/docs.html`
is a complete, self-contained document that Vite copies verbatim into the
bundle, so it is served by `npm run dev` and by `main.py` alike with no route
on either side. Porting it into JSX would duplicate the content and put its
typography in a fight with the app's Tailwind build; leaving it static costs
one `<a>` in
the footer. It reads the app's persisted theme out of `localStorage` and stamps
`data-theme` itself, so opening it from a dark app does not flash white. The
link is `/docs.html` and must stay that way -- FastAPI already owns `/docs`,
which is its Swagger UI.

The theme is the one piece of state React does not render: `main.jsx` writes
`data-theme` on `<html>` before the first paint and subscribes to the store to
keep it in step, so a reload into dark never flashes light and no component
re-renders to change a colour.

No router: `page` is a store key. Rows in `BrowseTable` are `memo`ised and read
their own open flag from the store, so expanding one row of two hundred
re-renders one row.

Tests are `node:test` on bare node -- `tests/schema.test.mjs` for the schema
translation, `tests/store.test.mjs` for the store, both via `npm test` in
`frontend/`. No jsdom, no test renderer. See `design.md` for the visual system.

## 11. What is deliberately absent

Redis, Celery, Docker, auth, rate limiting, script caching, concurrency. Each
is listed in `CLAUDE.md` §9 as backlog. Adding any of them requires a written
reason in the PR, per `rules.md`.
