import re
import sys
import time
from pathlib import Path

import pytest

from backend.executor import execute

# file:// -- no network, no third-party site (rules.md E23).
URL = (Path(__file__).parent / "fixtures" / "shop.html").resolve().as_uri()

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "price": {"type": "number"}},
    "required": ["name"],
}

GOOD = '''
def run(page):
    rows = []
    for card in page.query_selector_all("[data-testid^=product-]"):
        rows.append({
            "name": card.query_selector("h3").inner_text(),
            "price": float(card.query_selector("span").inner_text().lstrip("$")),
        })
    return rows
'''


def _run(body: str, timeout: int = 60, schema: dict = SCHEMA):
    return execute(body, URL, schema, timeout=timeout)


def test_good_script_returns_rows():
    a = _run(GOOD)
    assert a.success and a.error is None
    assert len(a.output) == 10
    assert a.output[0] == {"name": "Runner One", "price": 10.0}


def test_infinite_loop_is_killed():
    t = time.monotonic()
    a = _run("def run(page):\n    while True:\n        pass\n", timeout=5)
    assert not a.success and "timed out after 5s" in a.error
    assert time.monotonic() - t < 10          # killed, not waited out


def test_exception_traceback_comes_back_verbatim():
    a = _run('def run(page):\n    raise ValueError("boom")\n')
    assert not a.success and "ValueError: boom" in a.error


def test_non_list_return_names_the_type():
    a = _run('def run(page):\n    return "not a list"\n')
    assert not a.success and "str" in a.error


def test_empty_list_is_a_failure():
    a = _run("def run(page):\n    return []\n")
    assert not a.success and "empty" in a.error


def test_missing_required_field_names_it():
    a = _run('def run(page):\n    return [{"price": 1.0}]\n')
    assert not a.success and "name" in a.error and "row 0" in a.error


def test_stray_print_does_not_break_result_parsing():
    a = _run('def run(page):\n    print("noise")\n    return [{"name": "x"}]\n')
    assert a.success, a.error
    assert a.output == [{"name": "x"}]


def test_non_dict_row_is_rejected():
    a = _run('def run(page):\n    return ["just a string"]\n')
    assert not a.success and "row 0" in a.error


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="Darwin aliases RLIMIT_AS to RLIMIT_RSS and rejects it; see harness.cap_memory",
)
def test_memory_hog_dies_and_the_caller_survives():
    a = _run("def run(page):\n    return [{'name': 'x' * 5_000_000_000}]\n", timeout=60)
    assert not a.success
    assert _run(GOOD).success          # the runner still works afterwards


def test_executor_never_evaluates_generated_code_in_process():
    """The one refactor that would quietly destroy the security model (rules.md A1)."""
    src = (Path(__file__).parents[1] / "backend" / "executor.py").read_text()
    src = re.sub(r"^\s*#.*$", "", src, flags=re.M)          # comments don't execute
    for banned in ("exec(", "eval(", "importlib", "__import__"):
        assert banned not in src, f"executor.py must not use {banned}"
