"""The `jobs` and `script_attempts` tables, and the saved-script lookup.

The connection itself lives in backend/mysql.py -- a leaf, so the companies
feature opens one the same way. Parameterized queries only (rules.md A5).
No ORM, no migrations (rules.md D18).
"""
import json
import uuid
from typing import Any

from backend.config import STALE_RUNNING_MIN
# Re-exported: main.py catches `db.Unavailable` to answer 503, and every caller
# of this module already imports this one.
from backend.mysql import Unavailable, cursor as _cur  # noqa: F401


def _row(r: dict | None) -> dict | None:
    """MySQL hands back JSON columns as text and booleans as 0/1."""
    if r is None:
        return None
    for k in ("json_schema", "output_json"):
        if isinstance(r.get(k), (str, bytes)):
            r[k] = json.loads(r[k])
    if "success" in r:
        r["success"] = bool(r["success"])
    return r


def create_job(
    url: str, json_schema: dict, prompt: str, name: str | None = None
) -> uuid.UUID:
    job_id = uuid.uuid4()
    with _cur() as cur:
        cur.execute(
            "insert into jobs (id, name, url, json_schema, prompt, status)"
            " values (%s, %s, %s, %s, %s, 'pending')",
            (str(job_id), name, url, json.dumps(json_schema), prompt),
        )
    return job_id


def rename_job(job_id: uuid.UUID, name: str | None) -> None:
    """The one mutable field on a job.

    `updated_at = updated_at` keeps MySQL's on-update clock still: it is what
    fail_stale_running measures a `running` job against, and renaming one is
    not a sign of life.
    """
    with _cur() as cur:
        cur.execute(
            "update jobs set name = %s, updated_at = updated_at where id = %s",
            (name, str(job_id)),
        )


def set_status(job_id: uuid.UUID, status: str, *, error: str | None = None) -> None:
    with _cur() as cur:
        cur.execute(
            "update jobs set status = %s, error = %s, updated_at = now()"
            " where id = %s",
            (status, error, str(job_id)),
        )


def get_job(job_id: uuid.UUID) -> dict | None:
    with _cur() as cur:
        cur.execute("select * from jobs where id = %s", (str(job_id),))
        return _row(cur.fetchone())


def add_attempt(
    job_id: uuid.UUID,
    n: int,
    code: str,
    error: str | None,
    output: list[dict] | None,
    success: bool,
) -> None:
    with _cur() as cur:
        cur.execute(
            "insert into script_attempts"
            " (id, job_id, attempt_number, script_code, error_message,"
            "  output_json, success)"
            " values (%s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                str(job_id),
                n,
                code,
                error,
                json.dumps(output) if output is not None else None,
                success,
            ),
        )


def find_cached_script(url: str, json_schema: dict, prompt: str) -> str | None:
    """The most recent script that already succeeded for this exact job.

    Key is url + prompt + schema: a different prompt against the same page
    wants different data, so replaying would return the wrong shape.

    # ponytail: unindexed scan -- jobs.url is TEXT and can't be indexed without
    # a prefix length. `alter table jobs add index (url(255))` when it hurts.
    """
    with _cur() as cur:
        cur.execute(
            "select a.script_code"
            " from script_attempts a join jobs j on j.id = a.job_id"
            " where a.success = 1 and j.url = %s and j.prompt = %s"
            # cast: MySQL then compares JSON by value, so key order in the
            # incoming schema does not decide a cache hit.
            "   and j.json_schema = cast(%s as json)"
            " order by a.created_at desc limit 1",
            (url, prompt, json.dumps(json_schema)),
        )
        row = cur.fetchone()
        return row["script_code"] if row else None


def list_jobs_for(url: str, json_schema: dict, prompt: str,
                  limit: int = 20) -> list[dict[str, Any]]:
    """Every job ever run against this exact url + schema + prompt, newest first.

    The same key find_cached_script matches on, which is what makes this "one
    company's history": the batch creates a fresh job per pass, so a company is
    many jobs of few attempts rather than one job of many.

    # ponytail: the same unindexed scan as find_cached_script, and it wants the
    # same `index (url(255))` on the same day.
    """
    with _cur() as cur:
        cur.execute(
            "select j.id, j.name, j.status, j.error, j.created_at,"
            "       count(a.id) as attempts"
            "  from jobs j left join script_attempts a on a.job_id = j.id"
            " where j.url = %s and j.prompt = %s"
            "   and j.json_schema = cast(%s as json)"
            " group by j.id order by j.created_at desc limit %s",
            (url, prompt, json.dumps(json_schema), limit),
        )
        return [_row(r) for r in cur.fetchall()]


def get_attempts(job_id: uuid.UUID) -> list[dict[str, Any]]:
    with _cur() as cur:
        cur.execute(
            "select * from script_attempts where job_id = %s order by attempt_number",
            (str(job_id),),
        )
        return [_row(r) for r in cur.fetchall()]


def list_jobs(limit: int, offset: int) -> list[dict[str, Any]]:
    """Every job, newest first, with its attempt count -- the browse page."""
    with _cur() as cur:
        cur.execute(
            "select j.*, count(a.id) as attempts"
            " from jobs j left join script_attempts a on a.job_id = j.id"
            " group by j.id order by j.created_at desc limit %s offset %s",
            (limit, offset),
        )
        return [_row(r) for r in cur.fetchall()]


def list_attempts(limit: int, offset: int) -> list[dict[str, Any]]:
    """Every attempt ever made, newest first, carrying its job's url."""
    with _cur() as cur:
        cur.execute(
            "select a.*, j.url"
            " from script_attempts a join jobs j on j.id = a.job_id"
            " order by a.created_at desc limit %s offset %s",
            (limit, offset),
        )
        return [_row(r) for r in cur.fetchall()]


def list_scripts(limit: int, offset: int) -> list[dict[str, Any]]:
    """The saved-script store: one row per successful script, with how many
    times it was later replayed (attempt 0 -- see retry_loop.py)."""
    with _cur() as cur:
        cur.execute(
            "select j.url, j.prompt, j.json_schema, a.script_code,"
            "       a.created_at, a.job_id,"
            "       (select count(*) from script_attempts r"
            "          join jobs rj on rj.id = r.job_id"
            "         where r.attempt_number = 0 and rj.url = j.url"
            "           and rj.prompt = j.prompt"
            "           and rj.json_schema = j.json_schema) as reuse_count"
            " from script_attempts a join jobs j on j.id = a.job_id"
            " where a.success = 1 and a.attempt_number > 0"
            " order by a.created_at desc limit %s offset %s",
            (limit, offset),
        )
        return [_row(r) for r in cur.fetchall()]


def fail_stale_running(minutes: int = STALE_RUNNING_MIN) -> int:
    """Close out jobs whose process died mid-run. Nothing will ever finish them,
    and a job stuck in `running` is the one state the frontend cannot recover
    from. Returns how many were swept."""
    with _cur() as cur:
        return cur.execute(
            "update jobs set status = 'failed',"
            " error = 'interrupted -- the server restarted while this job was running',"
            " updated_at = now()"
            " where status = 'running' and updated_at < now() - interval %s minute",
            (minutes,),
        )
