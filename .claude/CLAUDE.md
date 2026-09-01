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
- **The broker directory is a driver over the jobs loop, not a second one.**
  A company's scrape *is* a job: same recon, same generation, same sandbox,
  same repair loop. `companies/runner.py` only decides the order of the batch
  and which of two calls to make -- `run_job(id)` may reach the model,
  `run_job(id, script=saved)` cannot. That is why "a manual run never spends
  money" needed no flag on the loop and no second execution path.
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
| Frontend | Vite + React 19, zustand for state, Tailwind v4 for styling | Form for input, polling view for job status/results. zustand's `persist` keeps the draft, the view and the running job across a refresh. Tailwind's `@theme` holds the design tokens, so the theme switch swaps values under the utilities and no component carries two class names |

No Docker/Kubernetes/message broker in v1. Add infrastructure only when the
simple version actually breaks under real load — not preemptively.

---

## 4. Folder structure

```
/backend                 # grouped by feature, not by layer
  main.py                # app assembly only: CORS, 503 handler, routers, static
  config.py              # env settings + every hard limit (stdlib-only leaf)
  contracts.py           # Attempt -- the one type three features share
  guardrails.py          # the three rails: submitted url, generated script,
                         #   and the scraped rows claiming to be people
  tracing.py             # Langfuse. A leaf everything may import and that
                         #   imports nothing: off unless LANGFUSE_* is set
  mysql.py               # the connection, shared by both db.py modules
  jobs/                  # a scrape request's whole life
    router.py            #   every HTTP route, and the background dispatch
    schemas.py           #   JobCreate / JobStatus: validation at the boundary
    db.py                #   MySQL: jobs + script_attempts, the saved-script lookup
    retry_loop.py        #   replay -> recon -> generate -> execute -> repair
  scraping/              # the browser -- the only package importing playwright
    recon.py             #   loads the page, reduces the DOM, follows one card
    executor.py          #   subprocess run + schema validation
    harness.py.tmpl      #   the wrapper the generated run() is pasted into
  llm/                   # the only package that talks to a model
    generate.py          #   builds the request, calls Gemini, extracts run()
    prompts.py           #   the frozen system prompt (the cached half)
  companies/             # the broker list, and the loan officers scraped off it
    router.py            #   CRUD on companies, the two batch buttons, GET /officers,
                         #   and the one row's whole history behind /detail
    schemas.py           #   CompanyIn: the same url rail jobs/schemas.py uses
    db.py                #   companies + loan_officers, and the officer upsert
    runner.py            #   the batch, and the frozen officer schema + prompt
    seed.py              #   python -m backend.companies.seed <csv>
  evals/                 # is the extracted data right? costs real LLM calls,
    cases.py             #   so it is not pytest. `python -m backend.evals.run`
    run.py               #   recon -> generate -> execute -> repair, then score
    sites/               #   local pages with known-correct expected rows
/frontend                # Vite + React 19 + zustand. `npm run dev` / `npm run build`
  index.html             # Vite entry
  vite.config.js         # dev server on :5173, build to ./dist
  public/
    docs.html            # the manual. Copied verbatim into the bundle by Vite,
                         #   so /docs.html works in dev and in the built app.
                         #   NOT /docs -- FastAPI already owns that (Swagger)
  src/
    main.jsx             # mounts <App/>
    App.jsx              # topbar + which page, and the one job poller
    store.js             # the zustand store: every piece of state, and persist.
                         #   `page` is the router; `companyId` is the only
                         #   argument one of them takes
    api.js               # API base and fetch helpers. No DOM, no React
    schema.js            # builder rows <-> JSON Schema
    columns.js           # {key,label,class,render} -> TanStack column defs.
                         #   The one part of a table that is ours rather than
                         #   the library's, so the one part with a test
    style.css            # the only CSS: @import tailwindcss, the @theme
                         #   tokens, and the [data-theme=dark] block that
                         #   swaps them. No component classes
    ui.js                # the class strings a repeated control would
                         #   otherwise spell out per call site: INPUT, GHOST,
                         #   TH. Plain text, so the scanner still sees them.
                         #   CARDS is the responsive half: under md a table
                         #   folds into one card per row, each cell a labelled
                         #   line. Descendant selectors on that one class, so
                         #   no row or cell names a second class for a phone
    pages/               # NewJob, Companies, Company (one row, its own page),
                         #   Browse, and the browse tab config
    components/          # Topbar, Footer, JobCard, SchemaBuilder, tables.
                         #   Table.jsx is the shell they share -- search box,
                         #   sortable header, drag-to-resize columns, scroll
                         #   box, pager -- and takes the rows as children,
                         #   because no two pages draw a row the same way.
                         #   The resize handler is ours, not TanStack's: it
                         #   starts from the width the column is rendering,
                         #   because most columns here take their width from a
                         #   class or from the space left over, and the
                         #   library's starts from a default it made up
    hooks/useJobPoll.js  # polls the watched job; reattaches after a refresh
CLAUDE.md                # this file
```

Each feature owns its whole vertical slice, and features never reach into one
another sideways: `scraping` never calls the LLM, `llm` never touches Playwright,
and only `jobs/retry_loop.py` imports both. Adding a feature is a new package
plus one `include_router` line in `main.py`. `tests/test_hardening.py` enforces
that table with an AST walk and fails on a module that has no row in it.

---

## 5. Data flow (detailed)

```
POST /jobs  { url, json_schema, prompt }
        │
        ▼
1. Create a `jobs` row, status = "pending". Return job_id immediately.
        │
        ▼ (background task starts)
2. SUPPLIED SCRIPT (jobs/retry_loop.py)
   - The request carried a `script`: run exactly that in the sandbox as
     attempt 0 and stop, done or failed. No recon, no LLM call, no repair --
     someone who pasted a script asked to run that script
   - No script: carry on to the reuse check
        │
        ▼
2b. REUSE CHECK (jobs/db.py, called from retry_loop.py)
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
4. GENERATE (llm/generate.py) — LLM call #1
   - Input: cleaned DOM summary + json_schema + prompt
   - Ask Claude for a Python script with a FIXED contract:
       def run(page) -> list[dict]
     The harness (scraping/executor.py) owns browser launch, retries, and output
     serialization — the generated script only implements extraction logic.
        │
        ▼
5. EXECUTE (scraping/executor.py)
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
  name          varchar(120),           -- optional user label; the only editable field
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
  attempt_number  int not null,   -- 0 = a script nobody generated for this job:
                                  --     the saved one replayed, or one supplied
                                  --     with the request. 1..3 = LLM-generated
  script_code     mediumtext not null,
  error_message   text,           -- null if this attempt succeeded
  output_json     json,           -- null if this attempt failed
  success         boolean not null,
  created_at      timestamp default current_timestamp,
  foreign key (job_id) references jobs(id),
  index script_attempts_job_id_idx (job_id)
);
```

```sql
create table if not exists companies (
  id            char(36) primary key,
  name          varchar(255) not null,  -- unique: what makes re-seeding idempotent
  nmls_id       varchar(32),
  lo_count      int,                    -- the sheet's own headcount, for comparison
  company_url   text,
  directory_url text,                   -- where the officers are listed
  note          text,                   -- a hint for the model ("Search Button")
  sheet_url     text,
  job_id        char(36),               -- the latest job run for this company
  last_error    text,                   -- why the last pass produced nothing
  created_at    timestamp(3) ...,
  updated_at    timestamp(3) ...
);

create table if not exists loan_officers (
  id          char(36) primary key,
  company_id  char(36) not null,        -- on delete cascade
  name        varchar(255) not null default '',   -- '' not null: two nulls
  nmls_id     varchar(32)  not null default '',   -- never collide in MySQL
  email       varchar(255),
  phone       varchar(64),
  address     text,
  `position`  varchar(255),             -- backticked: POSITION() is a function
  source_url  text,                     -- the page this row was scraped from
  fetched_at  timestamp(3) default current_timestamp(3),           -- first sighting
  updated_at  timestamp(3) ... on update current_timestamp(3),     -- last change
  dedupe_key  varchar(255) generated always as (if(nmls_id = '', name, nmls_id)) stored,
  unique key (company_id, dedupe_key)
);
```

`fetched_at` has no `on update` clause and `updated_at` does: that pair *is*
"when fetched / when updated". MySQL only fires `on update` when a value
actually differs, so a re-run over an unchanged page moves neither clock --
which is what makes `updated_at` mean something.

`script_attempts` keeps the full history of every attempt per job — useful for
debugging why a script failed, and it *is* the saved-script store: a row with
`success = 1`, joined to its job for the url/prompt/schema, is what the reuse
check reads back. There is deliberately no separate `cached_scripts` table to
keep in sync.

---

## 7. API surface (v1)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/jobs` | Create a job (`url`, `json_schema`, `prompt`, optional `name`, optional `script`). Returns `job_id`. |
| `GET` | `/jobs/{id}` | Poll job status. Returns status, the job's own `url`/`prompt`/`json_schema` (so a client holding only an id can re-run it), and once done: the result data + the final working script. |
| `PATCH` | `/jobs/{id}` | Rename a job (`name`). The only mutable field. |
| `GET` | `/jobs/{id}/attempts` | List all attempts for a job. Debugging. |
| `GET` | `/jobs` | List every job, newest first (`limit`, `offset`). |
| `GET` | `/attempts` | List every attempt across all jobs. |
| `GET` | `/scripts` | List saved scripts available for reuse, with `reuse_count`. |
| `GET` | `/companies` | The broker list, with each one's officer count and last run. |
| `POST` | `/companies` | Add a broker. |
| `PUT` | `/companies/{id}` | Replace the editable columns of one. |
| `DELETE` | `/companies/{id}` | Remove one, and the officers scraped for it. |
| `POST` | `/companies/scripts` | Background: write a script per company that lacks a working one. The only route here that can call the model. |
| `POST` | `/companies/run` | Background: replay every saved script, merge the officers. Never calls the model. |
| `GET` | `/companies/run` | `{running, phase, done, total, current}` -- the progress line. |
| `GET` | `/companies/{id}/detail` | One row expanded: its runs, the last run's attempts, the saved script, its officers. |
| `GET` | `/officers` | Scraped loan officers, newest change first. Read-only. |

---

## 8. Conventions for Claude Code when working in this repo

- **Never execute generated scripts in-process.** Always via `executor.py`'s
  subprocess runner. This is a hard security boundary, not a style
  preference.
- **All three guardrails stay deterministic.** `guardrails.py` is an `ast`
  walk, an `ipaddress` check and a handful of regexes. Never add a model-based
  rail: it would cost an LLM call per job to answer a question a syntax tree
  answers exactly. A rail's failure is a failed attempt the repair loop fixes,
  never an exception that kills the job.
- **The officer rail rejects the row, not the field.** A fourteen-digit NMLS id
  means the script read the wrong container for that card, so the address and
  phone beside it are mis-parsed too. Half a person in the database looks like
  a fact. It runs inside `companies/db.upsert_officers` -- the one door into
  `loan_officers` -- so no caller can walk around it, and when it rejects a
  whole harvest that becomes the company's `last_error`, which is what makes
  the next "Generate scripts" pass rewrite that site.
- **A guardrail change ships with both halves of its corpus.**
  `tests/test_guardrails.py` lists what must be blocked *and* the ordinary
  scraping code that must not be -- `ALLOWED`/`BLOCKED` for scripts,
  `KEEP`/`DROP` for officer rows. A rail with only the first list is one false
  positive away from burning every attempt on a job, or emptying 67 companies.
- **The evals live in `backend/evals/` but are not the app.** Nothing imports
  them at runtime, and the import table forbids them the database and
  `jobs/retry_loop.py`: an eval that could replay a saved script would be
  scoring the cache instead of the model, silently and flatteringly. The
  `loan-officers` case imports the real `OFFICER_PROMPT`/`OFFICER_SCHEMA`
  rather than a copy -- an eval against a copy measures the copy.
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
- **`name` is the only mutable column on a job.** `url`, `prompt` and
  `json_schema` are the reuse key, so editing one in place would silently
  re-point a saved script at a job it was never generated for. Changing what a
  job does means submitting a new one — which is what "Run again" loading the
  form already gives you.
- **A user-supplied script never reaches the LLM.** `POST /jobs` with a
  `script` runs that code in the sandbox and reports what happened. Do not
  "helpfully" fall through into the repair loop on failure — a replayed cache
  script does that because its inputs prove it was generated for this job;
  a pasted one is the user's own code, and rewriting it spends their money on
  a question they did not ask.
- **A replay is attempt 0, a generation is attempt 1-3.** That numbering is
  the cache-hit marker across the whole project (DB, API, both frontend
  pages). Do not renumber it, and do not let a replay spend one of the three
  LLM attempts.
- **Respect the retry cap (3 attempts).** Don't let the loop retry
  indefinitely — surface a clear failure to the user with the last error
  instead.
- **`OFFICER_SCHEMA` and `OFFICER_PROMPT` are frozen.** They are two thirds of
  the reuse key, so editing either is a deliberate "regenerate all 67 scripts"
  and should be treated as one. A company's `note` is the sanctioned way to
  change one site's prompt without touching the other sixty-six.
- **Generate may call the model; Run may not.** Keep the two buttons apart.
  Run all is the thing a user is expected to press on a schedule, and it is
  only safe to press because a company with no saved script is skipped rather
  than generated for.
- **Scraped officers are read-only.** The next run merges over them, so an
  edit would vanish without saying so. Making them editable means a `manual`
  flag the upsert skips -- do that deliberately or not at all.
- **Tracing may never change behaviour, and may never fail a job.** No keys
  means `tracing._client` is None and every call is a no-op object -- which is
  why the call sites carry no `if traced:`. It records what the loop did; it
  does not get a say in it, and nothing in the loop reads a span back.

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
- The batch runs one company at a time, in process. 67 sequential Playwright
  runs is minutes, and a server restart abandons the one in flight
- Nothing schedules the batch: "Run all" is a button somebody presses

These are acceptable gaps for v1 and should be treated as backlog, not as
bugs to silently "fix" by adding complexity.