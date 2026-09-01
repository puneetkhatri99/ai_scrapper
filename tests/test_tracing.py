"""Tracing is optional and has to stay that way: off it must cost nothing and
change nothing, on it must carry the tokens and the reason a job stopped.

No network in here. The client is pointed at an in-memory OTEL exporter, so
these assert on the spans that *would* have been sent (rules.md E22).
"""
import json
import uuid

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend import tracing
from backend.jobs import retry_loop
from backend.llm.generate import REPAIR_MODEL, generate
from backend.contracts import Attempt
from tests.test_generate import GOOD, RECON, SCHEMA, FakeClient
from tests.test_retry_loop import _attempt, _outcomes, rig  # noqa: F401  -- a fixture


@pytest.fixture(scope="module")
def _client():
    """One client for the file: it owns an OTEL provider and its threads, and
    building one per test is how a suite ends up waiting on four shutdowns."""
    exporter = InMemorySpanExporter()
    client = Langfuse(public_key="pk-lf-test", secret_key="sk-lf-test",
                      span_exporter=exporter)
    yield client, exporter
    client.shutdown()


@pytest.fixture
def spans(_client, monkeypatch):
    """Tracing on, exporting to memory. Overrides conftest's kill switch."""
    client, exporter = _client
    exporter.clear()
    monkeypatch.setattr(tracing, "_client", client)
    return exporter


def _attrs(span) -> dict:
    return {k.replace("langfuse.observation.", ""): v for k, v in span.attributes.items()}


def test_off_is_a_no_op(monkeypatch):
    """No keys means no client, and the call sites still read the same."""
    monkeypatch.setattr(tracing, "_client", None)
    with tracing.span("job", input={"a": 1}) as s:
        assert s is tracing.OFF
        s.update(output="ignored")
    tracing.update(output="ignored")
    tracing.flush()


def test_a_model_call_records_what_it_cost(spans):
    generate(RECON, SCHEMA, "get the names", client=FakeClient(GOOD))
    tracing.flush()

    (call,) = spans.get_finished_spans()
    a = _attrs(call)
    assert call.name == "write"
    assert json.loads(a["usage_details"]) == {
        "input": 1500, "output": 400, "cache_read_input_tokens": 0}
    # The raw text, not the extracted script: a missing fence is only readable
    # next to what the model actually said.
    assert "def run(page)" in a["output"]
    # The prompt is here on purpose. The key never is (rules.md A3).
    assert "authorization" not in json.dumps(a).lower()


def test_a_repair_is_a_separate_span_on_the_cheaper_model(spans):
    prior = Attempt(code="# old", output=None, error="TimeoutError", success=False)
    generate(RECON, SCHEMA, "get the names", prior, client=FakeClient(GOOD))
    tracing.flush()

    (call,) = spans.get_finished_spans()
    assert call.name == "repair"
    assert _attrs(call)["model.name"] == REPAIR_MODEL


def test_a_failed_generation_keeps_the_reason(spans):
    with pytest.raises(ValueError, match="no ```python fence"):
        generate(RECON, SCHEMA, "x", client=FakeClient("I would rather not."))
    tracing.flush()

    (call,) = spans.get_finished_spans()
    assert call.status.status_code.name == "ERROR"
    assert "no ```python fence" in call.status.description


def test_a_failed_job_says_why_and_how_many_attempts(spans, rig, monkeypatch):
    """The five questions this feature exists to answer, on one trace."""
    _outcomes(monkeypatch, _attempt(False, "a1"), _attempt(False, "a2"),
              _attempt(False, "a3"))
    retry_loop.run_job(uuid.uuid4())

    finished = spans.get_finished_spans()
    # Children close before the parent, so the job span is last.
    assert [s.name for s in finished] == [
        "recon", "attempt 1", "attempt 2", "attempt 3", "job"]

    job = _attrs(finished[-1])
    assert json.loads(job["output"]) == {"status": "failed", "error": "a3 broke"}
    assert job["level"] == "ERROR"
    assert json.loads(_attrs(finished[1])["output"])["success"] is False
