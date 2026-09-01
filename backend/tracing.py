"""Langfuse tracing: what the loop did, what it spent, and why it stopped.

The database already keeps every attempt, its script and its traceback. What it
cannot answer is the other half: how many tokens that cost, how long each step
took, what the model was actually sent, and where in a 67-company batch the run
is right now. That is what a trace is for, so this module adds one and changes
nothing else -- no step of the loop behaves differently when it is on.

**Off unless both keys are set.** No LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
means every call in here is a no-op object: no client, no background thread, no
network. Tracing is an observability tool, not a dependency of the product, and
a missing key must never fail a job.

**The API key never reaches a trace.** Call sites send the message list, never
the request headers, for the same reason nothing logs them (rules.md A3).

Stdlib plus langfuse only. No database, no playwright, no httpx -- every
package may import this one.
"""
from __future__ import annotations

import contextlib
import logging
import os
from typing import Any, Iterator

from langfuse import Langfuse

log = logging.getLogger(__name__)


class _Off:
    """The shape a call site uses, doing nothing.

    Returned instead of a real span when tracing is off, so the loop reads the
    same either way -- an `if traced:` around every step is how instrumentation
    ends up changing the thing it measures.
    """

    def update(self, **kw: Any) -> None:
        pass


OFF = _Off()


def _connect() -> Langfuse | None:
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return None
    # The SDK reads both keys and LANGFUSE_HOST from the environment itself, so
    # no secret passes through this file.
    client = Langfuse()
    log.info("langfuse tracing on, host=%s",
             os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))
    return client


# Resolved once, at import: config.load_env_file() has already run by now
# because every module imports config. Tests set this to None (conftest.py).
_client = _connect()


@contextlib.contextmanager
def span(name: str, **kw: Any) -> Iterator[Any]:
    """One step of the loop. The outermost open span is the trace."""
    if _client is None:
        yield OFF
        return
    with _client.start_as_current_observation(name=name, as_type="span", **kw) as s:
        yield s


@contextlib.contextmanager
def generation(name: str, **kw: Any) -> Iterator[Any]:
    """One model call. `usage_details` on it is what makes a trace cost money
    in the UI rather than just take time."""
    if _client is None:
        yield OFF
        return
    with _client.start_as_current_observation(name=name, as_type="generation", **kw) as g:
        yield g


def update(**kw: Any) -> None:
    """Stamp the enclosing span, without anyone having to hold on to it."""
    if _client is not None:
        _client.update_current_span(**kw)


def flush() -> None:
    """Send what is buffered.

    A job runs in a BackgroundTask that ends without anyone waiting on it, and
    the SDK batches by default -- so without this the trace of the job you are
    watching does not appear until some later job fills the buffer.
    """
    if _client is not None:
        _client.flush()
