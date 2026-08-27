# Plan 04 — Executor (the sandbox)

**Goal:** run LLM-written code safely, capture what it returned, validate it.
This is the hard security boundary (`rules.md` §A1). This module never talks to
Anthropic.

**Owner:** `backend-engineer`. `test-engineer` owns the failure-path suite —
that is most of this stage.

## Files

```
backend/executor.py
backend/harness.py.tmpl      # the wrapper the generated run() is pasted into
tests/test_executor.py
```

## The contract

```python
@dataclass
class Attempt:
    code: str
    output: list[dict] | None
    error: str | None
    success: bool

def execute(code, url, json_schema, timeout=60) -> Attempt
```

## The harness template

```python
import json, sys, resource
from playwright.sync_api import sync_playwright

# --- generated code is pasted here ---
{RUN_FUNCTION}
# -------------------------------------

if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000,) * 2)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        try:
            page.goto({URL!r}, wait_until="domcontentloaded", timeout=30_000)
            print("<<<RESULT>>>" + json.dumps(run(page)))
        finally:
            b.close()
```

The sentinel matters: generated scripts sometimes print despite instructions,
and Playwright itself writes to stdout. Parse only what follows `<<<RESULT>>>`.

## Steps

1. Write harness + code to a temp file (`tempfile.mkdtemp`, cleaned up after).
2. `subprocess.run([sys.executable, path], capture_output=True, text=True,
   timeout=timeout)` — never `exec`, never import it (`rules.md` §A1).
3. On `subprocess.TimeoutExpired` → `Attempt(success=False,
   error=f"timed out after {timeout}s")`.
4. Non-zero exit → the error is `stderr`, verbatim, tail-capped at ~4000 chars
   so it stays useful as LLM repair feedback without blowing up the prompt.
5. Split stdout on the sentinel; missing sentinel → error
   `"script produced no result"` plus the stderr tail.
6. `json.loads` the payload; not a list → error describing what it was.
7. **Validate** each row with `models.build_validator(json_schema)`. On failure,
   the error is the Pydantic message plus the offending row index — that is
   exactly what the repair prompt needs.
8. Empty list is a **failure** (`CLAUDE.md` §5) — a scraper that returns nothing
   did not work.
9. Return `Attempt`. This function raises nothing; every failure is a populated
   `error` field.

## Check (`test-engineer`) — the failure paths are the point

Each of these is one test, all against a `page.set_content` fixture or a
local `http.server`:

| Case | Expect |
|---|---|
| Known-good `run()` | `success=True`, rows match |
| `while True: pass` | `success=False`, error mentions timeout, wall-clock < timeout + 5s |
| `raise ValueError("boom")` | `success=False`, `"ValueError: boom"` in error |
| `return "not a list"` | `success=False`, error names the type |
| `return []` | `success=False` |
| Rows missing a required field | `success=False`, error names the field |
| `print("noise")` then valid return | `success=True` — sentinel parsing works |
| Script that allocates 5 GB | `success=False`, MemoryError-ish, server survives |

Plus one assertion that matters more than the rest: **`execute` never imports or
`exec`s the code.** Grep `executor.py` in the test for `exec(`/`eval(`/
`importlib` and fail if present. Cheap, and it catches the one refactor that
would quietly destroy the security model.

## Out of scope

Containers, seccomp, network egress filtering, per-domain robots handling.
`# ponytail: subprocess + rlimit + timeout; containerize when this runs untrusted user code at scale`
