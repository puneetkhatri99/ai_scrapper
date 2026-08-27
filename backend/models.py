"""Request/response models and the dynamic validator built from a user's
JSON Schema. Nothing here imports anything else in the project (architecture.md 2).
"""
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, create_model, field_validator

from backend.config import MAX_PROMPT_CHARS


class JobCreate(BaseModel):
    url: HttpUrl
    json_schema: dict
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme not in ("http", "https"):
            raise ValueError("url scheme must be http or https")
        return v

    @field_validator("json_schema")
    @classmethod
    def _is_schema(cls, v: dict) -> dict:
        if "type" not in v:
            raise ValueError("json_schema must be a JSON Schema object with a 'type'")
        return v


class JobStatus(BaseModel):
    id: uuid.UUID
    status: str
    attempts: int = 0
    replayed: bool = False     # attempt 0 exists: a saved script was reused
    result: list[dict] | None = None
    script: str | None = None
    error: str | None = None


@dataclass
class Attempt:
    """One generate -> execute -> validate round. Lives here, not in executor.py,
    because generate.py may not import executor.py (architecture.md 2)."""

    code: str
    output: list[dict] | None
    error: str | None          # traceback or validation message
    success: bool


_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def build_validator(json_schema: dict) -> type[BaseModel]:
    """Turn a user's JSON Schema into a Pydantic model for executor.py.

    Unknown properties are ignored; missing required ones fail.
    # ponytail: flat properties only -- nest via $defs when a user needs it
    """
    schema = json_schema
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        schema = schema["items"]

    props: dict = schema.get("properties") or {}
    required = set(schema.get("required") or ())

    fields: dict[str, Any] = {}
    for name, spec in props.items():
        py = _TYPES.get(spec.get("type") if isinstance(spec, dict) else None, Any)
        fields[name] = (py, ...) if name in required else (py | None, None)

    return create_model("RowValidator", **fields)
