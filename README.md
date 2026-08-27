# scarper

Describe the data you want; get a working scraper.

You give it a URL, a JSON schema, and a plain-English prompt. It looks at the
page with a real browser, asks Claude to write a Playwright extraction script,
runs that script in a sandbox, validates the output against your schema, and —
when the first draft fails, which is often — feeds the error back and tries
again. You get the data *and* the script that produced it.

The self-healing retry loop is the product. First-shot LLM scrapers break on
real sites constantly; the loop is what makes this usable.

A script that works is kept. Submit the same URL, prompt and schema again and
that saved script is replayed straight away: no browser recon, no LLM call, no
tokens. If the page has changed underneath it, the failed replay becomes the
repair context for a fresh generation, so a stale cache is never a dead end.

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

mysql -u root < schema.sql          # creates the ai_scripts database
```

The LLM is **xAI (Grok)**. Credentials come from the environment, read at call
time and never logged or written anywhere:

```bash
export XAI_API_KEY=xai-...             # or GROK_API_KEY
export GROK_MODEL=grok-4.6             # optional; grok-4.6 is the default
```

Check which models your key can actually reach:

```bash
curl -s https://api.x.ai/v1/models -H "authorization: Bearer $XAI_API_KEY" \
  | python -m json.tool
```

The Anthropic path this replaced is kept commented at the bottom of
[backend/generate.py](backend/generate.py). Prompt assembly and code extraction
are shared by both, so switching back is two edits.

MySQL defaults to `root@127.0.0.1:3306`, no password, database `ai_scripts`.
Override with `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` /
`MYSQL_DB`.

## Run

```bash
uvicorn backend.main:app --reload           # API on :8000
python -m http.server 5173 -d frontend      # UI on :5173
```

Open <http://127.0.0.1:5173>. Those two origins are the only ones CORS allows.

Two pages: **New job** builds the schema from form rows (with a raw-JSON
toggle) and watches the job run. **Browse** is a read-only view of every row in
both tables plus the saved scripts, with the result, script and error behind a
row click.

## A worked example

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H 'content-type: application/json' \
  -d '{
    "url": "https://books.toscrape.com/",
    "json_schema": {
      "type": "object",
      "properties": {"title": {"type": "string"}, "price": {"type": "string"}},
      "required": ["title"]
    },
    "prompt": "get the title and price of every book on the first two pages"
  }'
# {"job_id":"9f1c…"}

curl http://127.0.0.1:8000/jobs/9f1c…
# {"status":"done","attempts":2,"result":[{"title":"A Light in the Attic","price":"£51.77"}, …],
#  "script":"def run(page):\n    …"}
```

`attempts: 2` means the first script failed and the repair worked. To see what
the first one got wrong:

```bash
curl http://127.0.0.1:8000/jobs/9f1c…/attempts
```

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/jobs` | Create a job. Returns `job_id` immediately (202). |
| `GET` | `/jobs/{id}` | Poll status; carries `result` + `script` once `done`, `error` once `failed`. |
| `GET` | `/jobs/{id}/attempts` | Every generation attempt for one job, in order. |
| `GET` | `/jobs` | Every job, newest first. `limit` (1-500, default 100) and `offset`. |
| `GET` | `/attempts` | Every attempt across all jobs, newest first. Same paging. |
| `GET` | `/scripts` | Saved scripts available for reuse, with `reuse_count`. |
| `GET` | `/health` | `{"ok": true}` |

Attempt `0` is not a generation: it is a saved script being replayed. Attempts
`1`-`3` are the LLM's, and the cap of 3 counts only those.

`422` = your input was rejected (bad URL scheme, malformed schema, empty
prompt). `503` = the database is unreachable. Anything else that goes wrong
becomes a `failed` job with the real error in it, not an HTTP error.

## Tests

```bash
pytest -q
```

Nothing in the default suite calls the LLM API or touches a third-party site:
the HTTP client is stubbed, `tests/conftest.py` overrides `XAI_API_KEY` with a
fake one so a forgotten stub fails with a 401 instead of spending money, and
pages are served from `tests/fixtures/` over a local `http.server`. The suite
does need MySQL, and it cleans up after itself.

One test is skipped on macOS — see "memory limits" below.

## Limits

All of them are named in [backend/config.py](backend/config.py), nowhere else:

| | |
|---|---|
| Attempts per job | 3 |
| Script execution | 60s wall clock, 1.5 GB address space |
| Page load (recon) | 30s |
| Prompt length | 4,000 chars |
| Error tail fed back to the LLM | 4,000 chars |
| Generated script output | 16,000 tokens |
| One generation call | 300s, no retry behind it |
| Stale `running` sweep | 10 minutes |

**Memory limits do not apply on macOS.** Darwin aliases `RLIMIT_AS` to
`RLIMIT_RSS` and rejects any finite value, so a mac dev box bounds a runaway
script by the 60s timeout alone. Linux enforces it.

## Known limitations (v1, by design)

- One job at a time. No queue, no concurrency.
- Script reuse is keyed on the exact URL, prompt and schema. A different prompt
  against the same page regenerates; there is no per-domain reuse.
- No cache invalidation. A saved script is retired only by failing a replay.
- No auth, no rate limiting. The browse endpoints expose every job to anyone
  who can reach the port.
- Sites behind a login wall are not handled. A 403 or 401 fails the job with a
  message saying so rather than feeding a bot wall to the LLM.
- A server restart abandons any in-flight job. The next startup sweeps it into
  `failed`; re-running is your call.

These are backlog, not bugs. Each needs a measured reason before it gets built.

## Reading order

[CLAUDE.md](.claude/CLAUDE.md) — what this is and why the architecture is what
it is. [architecture.md](architecture.md) — where each thing lives and what may
import what. [rules.md](rules.md) — the 33 rules, each one there because
breaking it caused a specific problem.
