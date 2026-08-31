"""What the API accepts and returns. Validation at the trust boundary lives
here -- a url that is not http(s), a prompt over the cap, a schema with no
`type` never reaches a browser.
"""
import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, HttpUrl, field_validator

from backend import guardrails
from backend.config import MAX_NAME_CHARS, MAX_PROMPT_CHARS, MAX_SCRIPT_CHARS

# An empty box means "no name", not a name of "". Normalised here so the DB
# only ever holds null or a real label, and the same rule covers both the
# create and the rename.
Name = Annotated[
    str | None,
    Field(default=None, max_length=MAX_NAME_CHARS),
    AfterValidator(lambda v: (v or "").strip() or None),
]


class JobCreate(BaseModel):
    url: HttpUrl
    json_schema: dict
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    name: Name = None
    # Bring your own `def run(page)`. Given one, the loop runs exactly that in
    # the sandbox and stops -- no recon, no LLM call. The guardrail rail still
    # applies: it lives in executor.execute(), which every script goes through.
    script: Annotated[
        str | None,
        Field(default=None, max_length=MAX_SCRIPT_CHARS),
        AfterValidator(lambda v: (v or "").strip() or None),
    ] = None

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme not in ("http", "https"):
            raise ValueError("url scheme must be http or https")
        if reason := guardrails.check_url(str(v)):
            raise ValueError(reason)
        return v

    @field_validator("json_schema")
    @classmethod
    def _is_schema(cls, v: dict) -> dict:
        if "type" not in v:
            raise ValueError("json_schema must be a JSON Schema object with a 'type'")
        return v


class JobRename(BaseModel):
    """The whole of PATCH /jobs/{id}. Nothing else about a job is editable: url,
    prompt and schema are the reuse key, so changing one is a different job."""

    name: Name = None


class JobStatus(BaseModel):
    id: uuid.UUID
    status: str
    name: str | None = None
    # The three inputs, echoed back so a client holding only an id can re-run
    # this job: POST them again and retry_loop replays the saved script as
    # attempt 0. Without them the frontend can only re-run a job it still has
    # the form for, which a refresh loses.
    url: str
    prompt: str
    json_schema: dict
    attempts: int = 0
    replayed: bool = False     # attempt 0 exists: a saved script was reused
    result: list[dict] | None = None
    script: str | None = None
    error: str | None = None
