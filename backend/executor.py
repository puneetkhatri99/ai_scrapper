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

from pydantic import ValidationError

from backend.config import EXEC_MEMORY_BYTES, EXEC_TIMEOUT, MAX_ERROR_CHARS
from backend.models import Attempt, build_validator

SENTINEL = "<<<RESULT>>>"
_TEMPLATE = (Path(__file__).parent / "harness.py.tmpl").read_text()


def _fail(code: str, error: str) -> Attempt:
    return Attempt(code=code, output=None, error=error, success=False)


def execute(code: str, url: str, json_schema: dict,
            timeout: int = EXEC_TIMEOUT) -> Attempt:
    """Run `code` (a `def run(page)`) against `url`. Raises nothing: every
    failure comes back as a populated `error` for the repair prompt."""
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

    return Attempt(code=code, output=rows, error=None, success=True)
