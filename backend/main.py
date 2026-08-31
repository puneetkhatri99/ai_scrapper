"""App assembly: middleware, the database-down handler, the feature routers,
and the built frontend. Every route lives in a feature package -- adding one is
a new package plus one `include_router` line here.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.companies.router import router as companies_router
from backend.jobs import db
from backend.jobs.router import router as jobs_router

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
    CORSMiddleware,
    allow_origins=ORIGINS,
    # PUT and DELETE edit a company, PATCH renames a job. Without them here
    # the browser's preflight fails and the request never leaves the page --
    # but only in `npm run dev`, where :5173 and :8000 are separate origins.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.exception_handler(db.Unavailable)
async def _database_down(request: Request, exc: Exception) -> JSONResponse:
    """503, not a 500 with a stack trace -- the caller can retry this one."""
    return JSONResponse(status_code=503, content={"detail": f"database unavailable: {exc}"})


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


app.include_router(jobs_router)
app.include_router(companies_router)


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
