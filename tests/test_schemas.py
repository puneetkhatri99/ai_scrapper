import pytest
from pydantic import ValidationError

from backend.jobs.schemas import JobCreate

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "price": {"type": "number"}},
    "required": ["name"],
}


def test_jobcreate_accepts_valid():
    j = JobCreate(url="https://example.com", json_schema=SCHEMA, prompt="get things")
    assert str(j.url).startswith("https://")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"url": "ftp://example.com"},          # bad scheme
        {"prompt": ""},                        # empty prompt
        {"prompt": "x" * 4001},                # over cap
        {"json_schema": "not a dict"},         # non-dict schema
        {"json_schema": {"properties": {}}},   # dict without "type"
    ],
)
def test_jobcreate_rejects(kwargs):
    base = {"url": "https://example.com", "json_schema": SCHEMA, "prompt": "ok"}
    with pytest.raises(ValidationError):
        JobCreate(**{**base, **kwargs})
