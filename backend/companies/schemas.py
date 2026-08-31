"""What the companies API accepts. Validation at the trust boundary lives here,
exactly as jobs/schemas.py does it -- and through the same URL rail, so a
company row cannot become the door an SSRF walks in by.
"""
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, field_validator

from backend import guardrails
from backend.config import MAX_PROMPT_CHARS

# A blank box means "not set", not a value of "". Normalised once here so the
# DB only ever holds null or something real -- the same rule jobs/schemas.py
# applies to a job name.
_Blank = AfterValidator(lambda v: (v or "").strip() or None)

Text = Annotated[str | None, Field(default=None, max_length=MAX_PROMPT_CHARS), _Blank]
Url = Annotated[str | None, Field(default=None, max_length=2_000), _Blank]


class CompanyIn(BaseModel):
    """One broker. The whole editable row: POST creates it, PUT replaces it.

    A full replace rather than a partial patch because the page always holds
    the whole row anyway, and a half-sent row is a column silently blanked.
    `job_id` and `last_error` are absent on purpose -- they are the runner's
    bookkeeping, not the user's.
    """

    name: Annotated[str, Field(min_length=1, max_length=255)]
    nmls_id: Annotated[str | None, Field(default=None, max_length=32), _Blank] = None
    lo_count: Annotated[int | None, Field(default=None, ge=0)] = None
    company_url: Url = None
    directory_url: Url = None
    note: Text = None
    sheet_url: Url = None

    @field_validator("company_url", "directory_url", "sheet_url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        """The same two checks JobCreate makes, because these become the url a
        browser is pointed at. A row is only as safe as the weakest way in."""
        if v is None:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("url scheme must be http or https")
        if reason := guardrails.check_url(v):
            raise ValueError(reason)
        return v
