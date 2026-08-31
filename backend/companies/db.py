"""The `companies` and `loan_officers` tables.

Parameterized queries only (rules.md A5). `position` is backticked everywhere:
POSITION() is a MySQL function and an unquoted column of that name is a parse
error waiting for the one query somebody forgets.
"""
import uuid
from typing import Any

from backend import guardrails
from backend.mysql import cursor as _cur

# The row as the API and the seed both hand it over. Order matters: it is the
# insert list, the update list and the PUT list, and keeping one tuple means a
# new column is one edit rather than four.
FIELDS = ("name", "nmls_id", "lo_count", "company_url", "directory_url",
          "note", "sheet_url")

_OFFICER_FIELDS = ("name", "nmls_id", "email", "phone", "address", "position")


# --- companies --------------------------------------------------------------

def list_companies() -> list[dict[str, Any]]:
    """Every company, with how many officers we hold for it and the status of
    its last run -- the whole Companies page in one query."""
    with _cur() as cur:
        cur.execute(
            "select c.*, count(o.id) as officers, j.status as job_status"
            "  from companies c"
            "  left join loan_officers o on o.company_id = c.id"
            "  left join jobs j on j.id = c.job_id"
            " group by c.id, j.status"
            " order by c.lo_count is null, c.lo_count desc, c.name"
        )
        return list(cur.fetchall())


def get_company(company_id: uuid.UUID) -> dict | None:
    with _cur() as cur:
        cur.execute("select * from companies where id = %s", (str(company_id),))
        return cur.fetchone()


def create_company(data: dict) -> uuid.UUID:
    company_id = uuid.uuid4()
    with _cur() as cur:
        cur.execute(
            f"insert into companies (id, {', '.join(FIELDS)})"
            f" values ({', '.join(['%s'] * (len(FIELDS) + 1))})",
            (str(company_id), *(data[f] for f in FIELDS)),
        )
    return company_id


def add_missing(rows: list[dict]) -> int:
    """Insert the companies that are not here yet, leaving the ones that are
    exactly as they are. Returns how many were added.

    `id = id` rather than `insert ignore`: it skips a name we already hold
    without also silencing a genuine error on the other columns. Non-
    destructive on purpose -- the CSV is a one-time import and the UI is where
    a row is edited afterwards, so a second seed run must not undo edits.
    """
    if not rows:
        return 0
    with _cur() as cur:
        return cur.executemany(
            f"insert into companies (id, {', '.join(FIELDS)})"
            f" values ({', '.join(['%s'] * (len(FIELDS) + 1))})"
            " on duplicate key update id = id",
            [(str(uuid.uuid4()), *(r.get(f) for f in FIELDS)) for r in rows],
        )


def update_company(company_id: uuid.UUID, data: dict) -> None:
    """A full replace of the editable columns. `job_id` and `last_error` are
    the runner's, not the user's, so a PUT never touches them."""
    with _cur() as cur:
        cur.execute(
            f"update companies set {', '.join(f + ' = %s' for f in FIELDS)}"
            " where id = %s",
            (*(data[f] for f in FIELDS), str(company_id)),
        )


def delete_company(company_id: uuid.UUID) -> int:
    """Its officers go with it -- `on delete cascade` in schema.sql."""
    with _cur() as cur:
        return cur.execute("delete from companies where id = %s", (str(company_id),))


def set_company_run(company_id: uuid.UUID, job_id: uuid.UUID | None,
                    error: str | None) -> None:
    """What the last pass over this company did. `error` is null on success."""
    with _cur() as cur:
        cur.execute(
            "update companies set job_id = %s, last_error = %s where id = %s",
            (str(job_id) if job_id else None, error, str(company_id)),
        )


# --- loan officers ----------------------------------------------------------

def upsert_officers(company_id: uuid.UUID, source_url: str,
                    rows: list[dict]) -> tuple[int, list[str]]:
    """Merge a run's extracted rows into `loan_officers`.

    Returns (kept, rejected):

    `kept` is how many rows got past the officer rail and were merged --
    deliberately not MySQL's affected-row count, which is 0 when every officer
    is unchanged. A caller asking "did this run produce people?" must not read
    a perfectly good idempotent re-run as a failure.

    `rejected` is one reason per row the officer rail turned away. The rail
    runs *here*, at the one door into this table, rather than in the caller:
    every path that could put a person in the database goes through this
    function, so this is the only place a guard cannot be walked around
    (rules.md H32). The reasons come back out because the caller is the one
    that can act on them -- see companies/runner._harvest.

    One row per officer, keyed on their NMLS id (their name when they have
    none) -- the generated `dedupe_key` column in schema.sql. A second run over
    an unchanged page therefore touches nothing, which is what leaves
    `updated_at` meaning "when this officer last actually changed".

    `fetched_at` is deliberately absent from the update list: it is the first
    sighting and never moves.
    """
    kept, rejected = [], []
    for row in rows:
        reason = guardrails.check_officer(row)
        if reason:
            rejected.append(reason)
        else:
            kept.append(row)
    if not kept:
        return 0, rejected

    cols = ", ".join(f"`{f}`" for f in _OFFICER_FIELDS)
    # Never overwrite something with nothing. Scripts vary in quality between
    # runs -- the repair loop rewrites them -- so a run that missed the email
    # this time must not delete the one the last run found. A field the site
    # genuinely dropped keeps its last known value, which for a phone number is
    # more use than a blank.
    # Table-qualified on the right: `new` aliases the same table, so a bare
    # column name in here is ambiguous, not the existing row.
    sets = ", ".join(
        f"`{f}` = if(new.`{f}` = '', loan_officers.`{f}`, new.`{f}`)"
        for f in _OFFICER_FIELDS)
    with _cur() as cur:
        # `as new` rather than the deprecated values(): MySQL 8.0.19+.
        cur.executemany(
            f"insert into loan_officers (id, company_id, {cols}, source_url)"
            f" values ({', '.join(['%s'] * (len(_OFFICER_FIELDS) + 3))}) as new"
            f" on duplicate key update {sets}, source_url = new.source_url",
            [(str(uuid.uuid4()), str(company_id),
              *(_text(r.get(f)) for f in _OFFICER_FIELDS), source_url)
             for r in kept],
        )
    return len(kept), rejected


def _text(v: Any) -> str:
    """Whatever the model put in the field, as a string the key can compare.

    Whitespace is collapsed, not just stripped, because half of it is not
    whitespace: scraped pages are full of &nbsp;, and "Jane\xa0Doe" and
    "Jane Doe" are the same person with two different dedupe keys -- which is
    a duplicate officer on the run after the site changes its markup.

    guardrails._clean does the same thing for the same reason, so the rail
    judges exactly the text this stores.
    """
    return "" if v is None else " ".join(str(v).split())


def list_officers(limit: int, offset: int,
                  company_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """Newest first, carrying the company name -- the Browse page's Officers tab."""
    where = "where o.company_id = %s " if company_id else ""
    args: tuple = (str(company_id),) if company_id else ()
    with _cur() as cur:
        cur.execute(
            "select o.*, c.name as company"
            "  from loan_officers o join companies c on c.id = o.company_id "
            f"{where}"
            "order by o.updated_at desc limit %s offset %s",
            (*args, limit, offset),
        )
        return list(cur.fetchall())
