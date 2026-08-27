import pytest
from pydantic import ValidationError

from backend.models import JobCreate, build_validator

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


def test_build_validator_accepts_conforming_row():
    V = build_validator(SCHEMA)
    row = V(name="shoe", price=12.5, extra="ignored")
    assert row.name == "shoe" and row.price == 12.5
    assert not hasattr(row, "extra")


def test_build_validator_rejects_missing_required():
    V = build_validator(SCHEMA)
    with pytest.raises(ValidationError):
        V(price=1.0)


def test_build_validator_rejects_wrong_type():
    V = build_validator(SCHEMA)
    with pytest.raises(ValidationError):
        V(name="shoe", price="not a number")


def test_build_validator_unwraps_array_schema():
    V = build_validator({"type": "array", "items": SCHEMA})
    assert V(name="shoe").name == "shoe"
