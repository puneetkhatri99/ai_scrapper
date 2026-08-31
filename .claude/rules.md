# rules.md

Rules for anyone — human or agent — writing code in this repo. Short list on
purpose. Each rule is here because breaking it causes a specific, known problem.

---

## A. Security (never negotiable)

1. **Generated code runs in a subprocess. Never `exec`, `eval`, or `import` it
   in-process.** It is LLM-written code executing against arbitrary third-party
   sites. A hostile or broken script must not be able to reach the server
   process. Every execution path goes through `scraping/executor.py`, which
   runs `guardrails.check_script` first: no imports, no `open`, no
   `eval`/`exec` family, no dunder attributes. Half the generation prompt is a
   page we did not write, so the check belongs after the model, on the
   artifact. A block is a failed attempt the loop repairs, never a raise.
2. **Every subprocess run has a wall-clock timeout and a memory rlimit.** No
   unbounded run, ever. Kill on expiry, capture what you got.
3. **Never log or persist the LLM API key.** It comes from `GEMINI_API_KEY`
   (or `GOOGLE_API_KEY`), read inside `llm/generate.py` at call time so it never sits in
   a module global or a config file. Never log it, never put it in a payload
   field, never commit it.
4. **Everything from outside is untrusted, at every boundary it crosses.**
   Three artifacts in this system were written by someone outside this repo,
   and each gets a deterministic rail in `guardrails.py`, called at the single
   place that artifact enters:
   - **The submitted URL**, in `jobs/schemas.py` and `companies/schemas.py`.
     Scheme must be http/https, and `guardrails.check_url` rejects a host that
     resolves onto loopback or a private range — that is an SSRF, not a
     scrape. Also validate `json_schema` is a real JSON Schema object and cap
     `prompt` length. Pydantic at the boundary, never ad-hoc ifs scattered
     around. `ALLOW_PRIVATE_URLS=1` is the local-development escape hatch and
     is off by default.
   - **The generated script**, in `scraping/executor.py` — see rule 1.
   - **The rows that script scrapes**, in `companies/db.upsert_officers`.
     `guardrails.check_officer` is the one that is about truth rather than
     safety: a harmless script can still return a button as a person, or an
     NMLS id with two licence numbers run together, and schema validation
     passes both because they are strings and the schema asked for strings. It
     rejects the whole row, never one field — a mis-parsed licence means the
     script read the wrong container, so everything beside it is suspect, and
     half a person in a database looks like a fact.

   Each rail sits at the one door, not in each caller (see H32), so nothing
   reaches a browser, a subprocess or `loan_officers` around the side.
5. **Never interpolate user input into SQL.** Parameterized queries only.

## B. Module boundaries

6. **Respect the import table in `architecture.md` §2.** The package is grouped by
   feature: `scraping/` never calls the LLM, `llm/` never touches Playwright,
   `jobs/retry_loop.py` is the only orchestrator, and a new backend module
   needs a row in that table or `test_hardening.py` fails.
7. **The generated script implements `def run(page) -> list[dict]` and nothing
   else.** No imports, no browser launch, no printing, no validation. If a
   prompt starts asking for a standalone script, that is a regression — fix
   the prompt.
8. **Schema validation lives in the harness.** Generated scripts return raw
   dicts. `scraping/executor.py` validates. Never duplicate schema logic into the LLM
   prompt.

## C. LLM usage

9. **Provider is Google Gemini, via its OpenAI-compatible `POST
   .../v1beta/openai/chat/completions`.** Two models, split by job:
   `GEMINI_MODEL` (default `gemini-3.7-flash`) writes the script,
   `GEMINI_REPAIR_MODEL` (default `gemini-3.1-flash-lite`) repairs it on
   attempts 2..3. Keep that split — a repair is a narrow, cheap call and must
   not bill at the writer's tier. Trying a different model is env, never code.
   The Anthropic path is kept commented in `llm/generate.py`; if you restore it,
   restore rules 10-12 with it.
10. **One POST per model, no backoff.** There is no SDK underneath doing
    retries any more. The single exception is `UNAVAILABLE` (429/503) on the
    writer, which steps down to `GEMINI_REPAIR_MODEL` once — a busy model is
    survivable, a bad key is not. Everything else fails the job with the
    provider's message rather than hiding behind a retry nobody can see. Do not
    grow this into a general backoff layer without a stated reason.
11. **An error response keeps its body.** Gemini puts the actual reason
    (unknown model, quota exhausted, bad key) in the body. Raise `httpx.HTTPStatusError`
    with the body in the message, never a bare status code.
12. **Keep the cache prefix frozen.** The system message (contract + rules)
    goes first, byte-identical every call; recon summary, schema, user prompt
    and prior errors follow. No timestamps, UUIDs, or unsorted `json.dumps()`
    in the prefix. xAI caches the prefix automatically, so breaking this
    silently doubles the bill. Assert `cached_tokens > 0` on the second call.
13. **Recon output stays compact.** If raw HTML reaches `llm/generate.py`, that is a
    bug. Prefer `data-testid` / `aria-label` / `id` over generated class names —
    LLMs write more durable selectors from stable attributes.
14. **Retry cap is 3 total attempts.** Not configurable upward without a stated
    reason. Surface the last error to the user instead of looping.

## D. Code

15. **Reuse before writing.** Check `contracts.py`, `jobs/schemas.py` and existing helpers first. The
    most common failure mode here is re-implementing something two files over.
16. **Stdlib and installed deps before new dependencies.** A new package needs a
    one-line justification in the PR. `urllib`, `json`, `re`, `subprocess`,
    `dataclasses`, `pathlib` cover most of what this project needs.
17. **No speculative abstraction.** No interface with one implementation, no
    factory for one product, no config value that never changes, no plugin
    system for a thing that has one case.
18. **New infrastructure requires a stated reason.** Redis, Celery, Docker, a
    message broker, an ORM migration framework — all deferred by design
    (`CLAUDE.md` §3). "It might scale later" is not a reason; a measured
    bottleneck is.
19. **Type hints on every public function.** Return types especially — the
    contracts in `architecture.md` §3 are the API between modules.
20. **Errors surface, they do not vanish.** No bare `except: pass`. Catch the
    specific exception class (`httpx.HTTPStatusError`, `httpx.TimeoutException`)
    — never one broad `except Exception` that hides a non-retryable 400.

## E. Tests

21. **Every non-trivial piece of logic leaves one runnable check behind.** The
    smallest thing that fails if the logic breaks. `pytest` files under
    `tests/`, no fixtures-of-fixtures, no mocking framework unless the real
    thing genuinely cannot run.
22. **Never call the live LLM API in tests.** Stub the client. `conftest.py`
    also overrides `GEMINI_API_KEY` for the whole suite, so a forgotten stub
    fails with a 401 instead of spending money. One optional,
    explicitly-marked integration test may hit the real API; it does not run
    in the default suite. The place that *does* spend money is
    `backend/evals/`, which is why it is not pytest: `python -m
    backend.evals.run`. It lives in the package but not in the app, and the
    import table forbids it the database and `jobs/retry_loop.py` — an eval
    that could replay a saved script would be scoring the cache instead of the
    model, silently and in the flattering direction.
23. **Never scrape a live third-party site in a unit test.** Serve a fixture
    HTML file from a local `http.server` or use Playwright's `page.set_content`.
    Tests that depend on someone else's uptime are not tests.
24. **Test the failure paths, not just the happy path.** Timeout, non-JSON
    stdout, schema mismatch, empty result, LLM returning prose instead of code.
    These are the ones that actually fire in production.

## F. Data

25. **`script_attempts` is append-only.** Never update a row to correct history.
    The audit trail of what the LLM actually produced is the point of the table.
26. **`jobs.status` is the single source of truth** the frontend polls. Update
    it exactly once per transition, and always set `updated_at`.

## G. Frontend

27. **Follow `design.md`.** Tokens in `@theme`, no hardcoded colors -- a
    colour is a `--color-*` token and therefore a utility (`bg-surface`,
    `text-mute`), never a hex in a class. Mono for anything code-or-data
    shaped, focus rings intact. There is no `dark:` variant in this app: the
    token values swap under `[data-theme="dark"]`, so one class name covers
    both themes. A control repeated across files names its utilities once in
    `src/ui.js`; a one-off stays inline at its call site.
28. **Show the real error.** Verbatim traceback in the error block. Never
    "Something went wrong".
29. **Vite + React + zustand, and no fourth thing.** `npm run dev` for
    development, `npm run build` for the bundle `main.py` serves. State lives
    in the one store in `src/store.js` -- no second store, no context provider
    doing the same job, no data-fetching library on top. Tailwind v4 is the
    styling layer -- `style.css` is tokens only, and every rule is a utility
    on the element it styles. Still no UI kit and no component library:
    `design.md` plus `src/ui.js` is the design system. There is no router:
    `page` is a key in the store.
    Add react-router only when these views need shareable URLs, and move
    `page` out of the store in the same change rather than keeping both.
    Four consequences that are rules, not notes:
    - **Never `dangerouslySetInnerHTML`.** Everything on the page is scraped
      third-party text or an LLM-written script. React escaping it by default
      is the entire XSS story for this app.
    - **State the user created survives a refresh; fetched data does not.**
      `persist`'s `partialize` in `store.js` is the list: draft, page, theme,
      browse tab, open rows, and the watched job's id. Adding `rows` or `job` to it
      would show yesterday's data on load. The id is what reattaches the
      poller to a job still running.
    - **Components subscribe to fields, not to the store.**
      `useStore((s) => s.draft.url)`, never `useStore()`. A selector returning
      a fresh object re-renders on every action; return primitives, or use
      `useShallow`.
    - **Actions mutate through `set((s) => ...)`.** The functional form never
      reads a state captured by an older render.
30. **Frontend logic that can be silently wrong gets a node test.**
    `tests/schema.test.mjs` and `tests/store.test.mjs`, run by `npm test` in
    `frontend/`. They use `node:test` and a fake `localStorage`/`fetch` only --
    no jsdom, no test renderer, no framework. Keep it that way: a store action
    is testable without a DOM, and that is most of the logic here.

## H. Working style

31. **Read before you write.** Trace the actual flow through the modules the
    change touches. The smallest diff in the wrong place is a second bug.
32. **Fix the root cause.** Before patching a symptom, grep every caller of the
    function you are about to change. One guard in the shared function beats a
    guard in each caller — and it fixes the siblings the ticket did not mention.
33. **Deliberate shortcuts get a `ponytail:` comment** naming the ceiling and
    the upgrade path, e.g.
    `# ponytail: single job at a time, add a queue when concurrency is real`.
34. **Do not "improve" the decisions in `CLAUDE.md` §2 without a reason.** The
    generated-script model, the self-healing loop, subprocess isolation, no
    broker, and recon-before-generation are all intentional.
