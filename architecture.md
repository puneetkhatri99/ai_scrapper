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
              (Playwright, no LLM)          (xAI HTTP call, no browser)   (subprocess, no LLM)

browser ──GET /jobs/{id}──▶ FastAPI ──▶ MySQL (status / result / final script)
```

## 2. Module boundaries (hard)

| Module | May import | May NOT touch | Owns |
|---|---|---|---|
| `config.py` | stdlib | everything else | Env settings and every hard limit |
| `main.py` | models, db, retry_loop | playwright, httpx-to-the-LLM, subprocess, pymysql | HTTP surface, request validation, background dispatch |
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

xAI (Grok) over plain HTTP: `POST https://api.x.ai/v1/chat/completions`, which
is OpenAI-compatible. No provider SDK.

- **Model:** `GROK_MODEL`, default `grok-4.6` (xAI's recommendation for code;
  `grok-4.5`, `grok-4.3` and `grok-3` are the other current IDs). Env-driven,
  so switching models is not a code change.
- **Credentials:** `XAI_API_KEY` or `GROK_API_KEY`, read inside `generate()` at
  call time. Never a module global, never logged (rules.md A3).
- **No SDK, no streaming, no retry layer.** One `httpx` POST with a
  `LLM_TIMEOUT` read timeout. A 429 or 500 fails the job with the provider's
  own message instead of disappearing into a backoff.
- **Errors keep their body.** xAI puts the reason (unknown model, no credits,
  bad key) in the response body, so a non-2xx raises `httpx.HTTPStatusError`
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

One page. Form (url, json_schema, prompt) → POST → poll `GET /jobs/{id}` every
2s → render result table + the working script. No router, no state library, no
build step in v1. See `design.md` for the visual system.

## 10. What is deliberately absent

Redis, Celery, Docker, auth, rate limiting, script caching, concurrency. Each
is listed in `CLAUDE.md` §9 as backlog. Adding any of them requires a written
reason in the PR, per `rules.md`.
