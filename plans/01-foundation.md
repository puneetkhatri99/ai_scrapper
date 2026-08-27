# Plan 01 — Foundation

**Goal:** an installable project with a MySQL schema, validated request
models, and a FastAPI app that starts. No scraping, no LLM.

**Owner:** `backend-engineer`

## Files

```
pyproject.toml
backend/__init__.py
backend/config.py
backend/db.py
backend/models.py
backend/main.py          # health route only for now
schema.sql
tests/test_models.py
```

## Steps

1. **Deps.** `fastapi`, `uvicorn`, `pymysql`, `pydantic`, `anthropic`,
   `playwright`, `pytest`. Nothing else. `playwright install chromium`.
2. **`config.py`** — read MySQL connect kwargs from env (`MYSQL_HOST`/`MYSQL_PORT`/`MYSQL_USER`/`MYSQL_PASSWORD`/`MYSQL_DB`), defaulting to `root`@`127.0.0.1` with no password on database `ai_scripts`.
   The Anthropic key is *not* read here; the SDK resolves it itself
   (`rules.md` §A3).
3. **`schema.sql`** — `create database ai_scripts` plus exactly the two tables from `CLAUDE.md` §6. Apply it with
   `mysql -u root < schema.sql`. No migration framework in v1 (`rules.md` §D18).
4. **`db.py`** — a `pymysql` connection per call, plus these functions and no
   others:
   ```python
   def create_job(url, json_schema, prompt) -> uuid.UUID
   def set_status(job_id, status, *, error=None) -> None
   def get_job(job_id) -> dict | None
   def add_attempt(job_id, n, code, error, output, success) -> None
   def get_attempts(job_id) -> list[dict]
   ```
   Parameterized queries only. `set_status` always bumps `updated_at`.
5. **`models.py`** — Pydantic:
   - `JobCreate`: `url: HttpUrl`, `json_schema: dict`, `prompt: str`
     (`min_length=1`, `max_length=4000`).
     Validator: `json_schema` must be a dict with `"type"` present.
   - `JobStatus`: `id`, `status`, `attempts`, `result`, `script`, `error`.
   - `build_validator(json_schema) -> type[BaseModel]` — turns the user's JSON
     Schema into a Pydantic model used by `executor.py`. Use
     `pydantic.create_model` on the top-level object properties; unknown
     properties are ignored, missing required ones fail.
     `# ponytail: flat properties only — nest via $defs when a user needs it`
6. **`main.py`** — `FastAPI()` + `GET /health` returning `{"ok": true}`.

## Check (`test-engineer`)

`tests/test_models.py`:
- `JobCreate` rejects `ftp://…`, an empty prompt, and a non-dict schema.
- `build_validator` accepts a conforming row, rejects a row missing a required
  field, and rejects a wrong-typed field.

`uvicorn backend.main:app` starts and `/health` returns 200.

## Out of scope

Auth, rate limiting, connection retry logic, migrations.
