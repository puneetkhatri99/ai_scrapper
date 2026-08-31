"""HTTP surface. Validates, persists, dispatches -- no business logic here.

Imports models, db and retry_loop only: no playwright, no anthropic, no
subprocess (rules.md B6).
"""
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import db, retry_loop
from backend.models import JobCreate, JobStatus

log = logging.getLogger(__name__)

FRONTEND = Path(__file__).parents[1] / "frontend" / "dist"

# ponytail: fixed local origins, never "*" (plan 06). Move to config.py the
# day this is served from anywhere but a dev box.
ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:8000", "http://127.0.0.1:8000",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Nothing resumes a half-run job (plan 08 §1): the process that owned it is
    # gone. Close them out so no job sits in `running` forever.
    try:
        swept = db.fail_stale_running()
        if swept:
            log.warning("swept %d stale running job(s) into failed", swept)
    except db.Unavailable as e:
        log.warning("startup sweep skipped, database unreachable: %s", e)
    yield


app = FastAPI(title="scarper", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"]
)


@app.exception_handler(db.Unavailable)
async def _database_down(request: Request, exc: Exception) -> JSONResponse:
    """503, not a 500 with a stack trace -- the caller can retry this one."""
    return JSONResponse(status_code=503, content={"detail": f"database unavailable: {exc}"})


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/jobs", status_code=202)
def create_job(job: JobCreate, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Returns before any work starts -- that is the point of the async shape."""
    job_id = db.create_job(str(job.url), job.json_schema, job.prompt)
    background_tasks.add_task(retry_loop.run_job, job_id)
    return {"job_id": str(job_id)}


# --- browse: read-only views over both tables (frontend/browse.html) -------
# Capped server-side: script_code is mediumtext, so an uncapped limit would
# pull every script ever generated in one response.
_Limit = Annotated[int, Query(ge=1, le=500)]
_Offset = Annotated[int, Query(ge=0)]


@app.get("/jobs")
def list_jobs(limit: _Limit = 100, offset: _Offset = 0) -> list[dict]:
    return db.list_jobs(limit, offset)


@app.get("/attempts")
def list_attempts(limit: _Limit = 100, offset: _Offset = 0) -> list[dict]:
    return db.list_attempts(limit, offset)


@app.get("/scripts")
def list_scripts(limit: _Limit = 100, offset: _Offset = 0) -> list[dict]:
    """Saved scripts available for reuse, with how often each was replayed."""
    return db.list_scripts(limit, offset)


def _job_or_404(job_id: uuid.UUID) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@app.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID) -> JobStatus:
    job = _job_or_404(job_id)
    attempts = db.get_attempts(job_id)
    # The winning attempt carries both deliverables: the data and the script.
    won = next((a for a in attempts if a["success"]), None)
    return JobStatus(
        id=job["id"],
        status=job["status"],
        attempts=len(attempts),
        replayed=any(a["attempt_number"] == 0 for a in attempts),
        result=won["output_json"] if won else None,
        script=won["script_code"] if won else None,
        error=job["error"],
    )


@app.get("/jobs/{job_id}/attempts")
def get_attempts(job_id: uuid.UUID) -> list[dict]:
    """Raw history -- what the LLM actually wrote, for when a job fails."""
    _job_or_404(job_id)
    return db.get_attempts(job_id)


# --- the frontend ----------------------------------------------------------
# Mounted last, so it only ever answers paths no route above claimed. This is
# the built bundle: `cd frontend && npm run build`. Serving it here puts the
# page on the same origin as the API, so CORS never enters into it.
#
# Absent before the first build, and absent by design during development --
# `npm run dev` serves :5173 with hot reload and talks to :8000 cross-origin,
# which is why that origin is in ORIGINS above.
if FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
