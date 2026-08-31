"""The sandbox. Runs LLM-written code in a subprocess, captures what it
returned, validates it against the user's schema.

Never `exec`s, `eval`s or imports the generated code -- that is the hard
security boundary (rules.md A1), not a style choice. Never talks to Anthropic
(architecture.md 2).

# ponytail: subprocess + rlimit + timeout. Containerize when this runs
# untrusted user code at scale.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError, create_model

from backend import guardrails
from backend.config import EXEC_MEMORY_BYTES, EXEC_TIMEOUT, MAX_ERROR_CHARS
from backend.contracts import Attempt

# Schema validation is the harness's job, never the generated script's
# (rules.md). It lives here because execute() is the only caller.
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
    """Turn a user's JSON Schema into a Pydantic model for execute() below.

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


SENTINEL = "<<<RESULT>>>"
_TEMPLATE = (Path(__file__).parent / "harness.py.tmpl").read_text()


def _fail(code: str, error: str) -> Attempt:
    return Attempt(code=code, output=None, error=error, success=False)


def execute(code: str, url: str, json_schema: dict,
            timeout: int = EXEC_TIMEOUT,
            row_check: Callable[[dict], str | None] | None = None) -> Attempt:
    """Run `code` (a `def run(page)`) against `url`. Raises nothing: every
    failure comes back as a populated `error` for the repair prompt.

    `row_check` is an optional second opinion on each row, applied after the
    schema passes it. The schema rules on *shape* and cannot rule on truth: a
    button scraped as a person and a licence number with two ids run together
    are both strings, and the schema asked for strings. A caller that knows
    what its rows mean passes a rail here -- `companies/runner.py` passes
    `guardrails.check_officer` -- and a rejection becomes an ordinary failed
    attempt, so the model gets the reason and repairs the selector. Being here
    rather than at the end of the pipeline is the whole point: this is the only
    place a bad extraction can still be turned into a good one.
    """
    # The script rail sits here, not in generate.py, because this is the only
    # function that ever runs a script -- so a replayed one off the cache is
    # checked too, and a block reads as an ordinary failed attempt that the
    # repair loop feeds back to the model.
    if reason := guardrails.check_script(code):
        return _fail(code, reason)

    # Markers substituted longest-lived first, so a url or a generated script
    # containing a marker string can't corrupt a later replacement.
    script = (
        _TEMPLATE.replace("__MEM__", str(EXEC_MEMORY_BYTES))
        .replace("__URL__", repr(url))
        .replace("# __RUN_FUNCTION__", code)
    )

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "job.py"
        path.write_text(script)
        try:
            proc = subprocess.run(
                [sys.executable, str(path)],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _fail(code, f"timed out after {timeout}s")

    stderr = proc.stderr[-MAX_ERROR_CHARS:]
    if proc.returncode != 0:
        return _fail(code, stderr or f"script exited {proc.returncode} with no stderr")

    if SENTINEL not in proc.stdout:
        return _fail(code, f"script produced no result\n{stderr}")
    # json.dumps never emits a newline, so the payload is the rest of that line.
    payload = proc.stdout.split(SENTINEL, 1)[1].split("\n", 1)[0]

    try:
        rows = json.loads(payload)
    except json.JSONDecodeError as e:
        return _fail(code, f"result was not valid JSON: {e}")

    if not isinstance(rows, list):
        return _fail(code, f"run() returned {type(rows).__name__}, expected list[dict]")
    if not rows:
        return _fail(code, "run() returned an empty list -- nothing was extracted")

    validator = build_validator(json_schema)
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            return _fail(code, f"row {i} is {type(row).__name__}, expected dict")
        try:
            validator.model_validate(row)
        except ValidationError as e:
            return _fail(code, f"row {i} failed schema validation: {e}")
        if row_check and (why := row_check(row)):
            return _fail(code, f"row {i} is not what was asked for: {why}")

    return Attempt(code=code, output=rows, error=None, success=True)
