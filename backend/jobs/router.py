"""The jobs feature's HTTP surface. Validates, persists, dispatches -- no
business logic here, that is retry_loop.py's job (architecture.md 2).

Imports db, schemas and retry_loop only: no playwright, no httpx, no
subprocess (rules.md B6).
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from backend.jobs import db, retry_loop
from backend.jobs.schemas import JobCreate, JobRename, JobStatus

router = APIRouter(tags=["jobs"])


@router.post("/jobs", status_code=202)
def create_job(job: JobCreate, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Returns before any work starts -- that is the point of the async shape."""
    job_id = db.create_job(str(job.url), job.json_schema, job.prompt, job.name)
    background_tasks.add_task(retry_loop.run_job, job_id, job.script)
    return {"job_id": str(job_id)}


# --- browse: read-only views over both tables (the frontend's Browse page) -
# Capped server-side: script_code is mediumtext, so an uncapped limit would
# pull every script ever generated in one response.
_Limit = Annotated[int, Query(ge=1, le=500)]
_Offset = Annotated[int, Query(ge=0)]


@router.get("/jobs")
def list_jobs(limit: _Limit = 100, offset: _Offset = 0) -> list[dict]:
    return db.list_jobs(limit, offset)


@router.get("/attempts")
def list_attempts(limit: _Limit = 100, offset: _Offset = 0) -> list[dict]:
    return db.list_attempts(limit, offset)


@router.get("/scripts")
def list_scripts(limit: _Limit = 100, offset: _Offset = 0) -> list[dict]:
    """Saved scripts available for reuse, with how often each was replayed."""
    return db.list_scripts(limit, offset)


def _job_or_404(job_id: uuid.UUID) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID) -> JobStatus:
    job = _job_or_404(job_id)
    attempts = db.get_attempts(job_id)
    # The winning attempt carries both deliverables: the data and the script.
    won = next((a for a in attempts if a["success"]), None)
    return JobStatus(
        id=job["id"],
        status=job["status"],
        name=job["name"],
        url=job["url"],
        prompt=job["prompt"],
        json_schema=job["json_schema"],
        attempts=len(attempts),
        replayed=any(a["attempt_number"] == 0 for a in attempts),
        result=won["output_json"] if won else None,
        script=won["script_code"] if won else None,
        error=job["error"],
    )


@router.patch("/jobs/{job_id}")
def rename_job(job_id: uuid.UUID, patch: JobRename) -> dict[str, str | None]:
    """Rename a job. Returns the stored name -- blank comes back as null."""
    _job_or_404(job_id)
    db.rename_job(job_id, patch.name)
    return {"name": patch.name}


@router.get("/jobs/{job_id}/attempts")
def get_attempts(job_id: uuid.UUID) -> list[dict]:
    """Raw history -- what the LLM actually wrote, for when a job fails."""
    _job_or_404(job_id)
    return db.get_attempts(job_id)
