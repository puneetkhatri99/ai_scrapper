# Plan 00 — Overview & build order

Read `CLAUDE.md`, then `architecture.md`, then `rules.md`. Each stage below has
its own plan file. Build them in order — each one is runnable on its own before
the next begins.

| # | Stage | File | Ships when |
|---|---|---|---|
| 01 | Foundation — deps, config, DB, models | [01-foundation.md](01-foundation.md) | `pytest` green, tables exist, health endpoint responds |
| 02 | Recon — Playwright DOM reduction | [02-recon.md](02-recon.md) | `recon(url)` returns a compact `Recon` on a fixture page |
| 03 | Generate — Anthropic call, prompt, caching | [03-generate.md](03-generate.md) | Returns a syntactically valid `run(page)` from a stubbed client |
| 04 | Executor — subprocess sandbox + validation | [04-executor.md](04-executor.md) | Runs a known-good script, catches timeout/crash/schema-fail |
| 05 | Retry loop — orchestration + attempt history | [05-retry-loop.md](05-retry-loop.md) | Fails twice, succeeds on third, all three rows persisted |
| 06 | API — routes, background dispatch, polling | [06-api.md](06-api.md) | End-to-end `POST /jobs` → `GET /jobs/{id}` = `done` |
| 07 | Frontend — form + poll view | [07-frontend.md](07-frontend.md) | A human can run a scrape without touching curl |
| 08 | Hardening — failure paths, limits, docs | [08-hardening.md](08-hardening.md) | Failure-path tests pass, README written |

## Agents

Three agents live in `.claude/agents/`. Use them per stage:

- **`backend-engineer`** (Opus) — designs and writes the module. Owns
  contracts, boundaries, and the LLM layer. Start every stage here.
- **`script-writer`** (Sonnet) — writes the concrete Playwright/extraction code
  and the prompt templates. Narrow, mechanical, fast.
- **`test-engineer`** (Sonnet) — writes and runs the checks, hunts the failure
  paths, reports real output. Never marks a stage done on a claim.

Loop per stage: `backend-engineer` designs → `script-writer` implements →
`test-engineer` verifies → fix → move on. No stage is "done" until
`test-engineer` has pasted actual passing output.

## Definition of done, every stage

1. Code respects the import table in `architecture.md` §2.
2. One runnable check exists and passes (`rules.md` §E).
3. No new dependency without a written reason.
4. Deliberate shortcuts carry a `ponytail:` comment.
