"""The companies feature's HTTP surface: CRUD on the broker list, the two
batch buttons, and a read-only view of what they extracted.

Validates, persists, dispatches -- the order of operations is runner.py's
(architecture.md 2). No playwright, no httpx, no subprocess, no pymysql.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from backend.companies import db, runner
from backend.companies.schemas import CompanyIn
from backend.jobs import db as jobs_db

router = APIRouter(tags=["companies"])

_Limit = Annotated[int, Query(ge=1, le=1000)]
_Offset = Annotated[int, Query(ge=0)]


class Batch(BaseModel):
    """Which companies a button applies to. Omitted means all of them, which
    is what the two page-level buttons send."""

    ids: set[str] | None = None


# --- the broker list --------------------------------------------------------

@router.get("/companies")
def list_companies() -> list[dict]:
    """Every company, with its officer count and the last run's outcome."""
    return db.list_companies()


@router.post("/companies", status_code=201)
def create_company(company: CompanyIn) -> dict[str, str]:
    return {"id": str(db.create_company(company.model_dump()))}


def _company_or_404(company_id: uuid.UUID) -> dict:
    company = db.get_company(company_id)
    if company is None:
        raise HTTPException(404, "company not found")
    return company


@router.put("/companies/{company_id}")
def update_company(company_id: uuid.UUID, company: CompanyIn) -> dict[str, str]:
    """Replace the editable columns. `job_id` and `last_error` are the
    runner's bookkeeping and are not part of the row a user can send."""
    _company_or_404(company_id)
    db.update_company(company_id, company.model_dump())
    return {"id": str(company_id)}


@router.delete("/companies/{company_id}", status_code=204)
def delete_company(company_id: uuid.UUID) -> None:
    """Deletes the officers scraped for it too -- `on delete cascade`."""
    _company_or_404(company_id)
    db.delete_company(company_id)


# --- the two buttons --------------------------------------------------------

def _start(background_tasks: BackgroundTasks, fn, ids: set[str] | None) -> dict[str, str]:
    """Claim the batch, or say who has it. Claimed and dispatched in the same
    breath so a claim can never outlive the request that took it."""
    if not runner.claim():
        raise HTTPException(409, "a run is already in progress")
    background_tasks.add_task(fn, ids)
    return {"started": fn.__name__}


@router.post("/companies/scripts", status_code=202)
def generate_scripts(batch: Batch, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Write a script for each company that has no working one. The only route
    in this feature that can call the model."""
    return _start(background_tasks, runner.generate_scripts, batch.ids)


@router.post("/companies/run", status_code=202)
def run_all(batch: Batch, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Replay every saved script and merge what it extracted. Never calls the
    model: a company with no saved script is skipped, not generated for."""
    return _start(background_tasks, runner.run_all, batch.ids)


@router.get("/companies/run")
def run_progress() -> dict:
    """What the batch is doing right now -- the page polls this while it runs."""
    return runner.progress()


@router.get("/companies/{company_id}/detail")
def company_detail(company_id: uuid.UUID) -> dict:
    """Everything about one company in one place: every pass ever made over it,
    what the last pass tried, the script it saved, and the people that script
    found.

    One request rather than four, because this is opened by clicking a row and
    a row that fires four fetches is a row that flickers.

    Attempts come back without `script_code` or `output_json`: the script worth
    reading is the saved one below, and the rows are the officers table. A
    200-officer attempt would otherwise be the largest thing on the page.
    """
    company = _company_or_404(company_id)
    url = runner.target_url(company)
    prompt = runner.build_prompt(company)
    heavy = ("script_code", "output_json")

    attempts = jobs_db.get_attempts(company["job_id"]) if company["job_id"] else []
    return {
        # The row itself: the page is reachable by id alone (a refresh, a
        # pasted link), so it cannot assume the list has been fetched.
        "company": company,
        "url": url,
        # No url means no reuse key, so there is nothing to look either up by.
        "jobs": jobs_db.list_jobs_for(url, runner.OFFICER_SCHEMA, prompt) if url else [],
        "attempts": [{k: v for k, v in a.items() if k not in heavy}
                     | {"rows": len(a["output_json"] or [])} for a in attempts],
        "script": (jobs_db.find_cached_script(url, runner.OFFICER_SCHEMA, prompt)
                   if url else None),
        "officers": db.list_officers(500, 0, company_id),
    }


# --- what came back ---------------------------------------------------------

@router.get("/officers")
def list_officers(limit: _Limit = 200, offset: _Offset = 0,
                  company_id: uuid.UUID | None = None) -> list[dict]:
    """Scraped loan officers, most recently changed first.

    Read-only on purpose: the next run merges over these rows, so a hand edit
    here would vanish without saying so.
    """
    return db.list_officers(limit, offset, company_id)
