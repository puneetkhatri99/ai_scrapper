# Plan 08 — Hardening & docs

**Goal:** the parts that only matter when something goes wrong. Nothing new is
built here — this stage makes the existing thing survivable.

**Owner:** `test-engineer` leads; `backend-engineer` fixes what it finds.

## 1. Failure-path sweep

Walk every module and confirm the failure is *visible*, not swallowed
(`rules.md` §D20):

- [ ] Target site is down / DNS fails → job `failed`, message names the URL
- [ ] Target site is 403 / bot-blocked → job `failed`, message says so
- [ ] Page never reaches `networkidle` → recon timeout, job `failed`
- [ ] Anthropic returns 429 → SDK retries; if it still fails, job `failed` with
      a clear message. No second retry layer of ours (`rules.md` §C).
- [ ] Anthropic returns 400 → **not** retried, job `failed` immediately
- [ ] Anthropic returns prose instead of code → `generate` raises, job `failed`
- [ ] MySQL is down at job start → `POST /jobs` returns 503, not a 500 trace
- [ ] Process restarts mid-job → job is stuck in `running`; document it and add
      a startup sweep that marks stale `running` rows older than 10 minutes as
      `failed`

## 2. Limits, stated in one place

Put these in `config.py` as named constants, not scattered magic numbers:

```python
MAX_ATTEMPTS      = 3          # rules.md §C14
EXEC_TIMEOUT      = 60         # seconds
RECON_TIMEOUT     = 30         # seconds
EXEC_MEMORY_BYTES = 1_500_000_000
MAX_PROMPT_CHARS  = 4_000
MAX_ERROR_CHARS   = 4_000      # error tail fed back to the LLM
STALE_RUNNING_MIN = 10
```

## 3. Cost visibility

Log per job: attempts used, `usage.input_tokens`, `usage.output_tokens`,
`usage.cache_read_input_tokens`. One line, structured.

**Assert in a test that `cache_read_input_tokens > 0` on the second generation
call** with a stubbed-but-counting client, or at minimum that the system block
is byte-identical across calls (`rules.md` §C12). A silently broken cache is
the single most expensive bug this project can have and it produces no error.

## 4. Docs

- `README.md` — setup (`pip install`, `playwright install chromium`,
  `mysql -u root < schema.sql`, `ANTHROPIC_API_KEY` or `ant auth login`,
  `uvicorn backend.main:app --reload`), one worked example, and the known
  limitations from `CLAUDE.md` §9.
- Run `/ponytail-debt` and confirm every `ponytail:` comment in the codebase
  names a real ceiling and an upgrade path.

## 5. Final review gate

- [ ] `architecture.md` §2 import table holds — grep each module's imports
- [ ] No `exec(`, `eval(`, or in-process import of generated code anywhere
- [ ] No `except: pass` and no bare `except Exception` that hides a 400
- [ ] No new dependency lacking a written reason
- [ ] Full `pytest` suite green, output pasted, not claimed

## Backlog (explicitly not now)

Script caching by domain + prompt hash, concurrency/queue, auth, rate limiting,
login-walled sites. All in `CLAUDE.md` §9. Each needs a measured reason before
it gets built (`rules.md` §D18).
