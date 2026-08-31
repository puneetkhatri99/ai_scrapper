"""Types that cross feature boundaries. Nothing else belongs here.

`Attempt` is produced by scraping.executor, consumed by jobs.retry_loop, and
named in llm.generate's signature -- three features, so it can live in none of
them (architecture.md 2 forbids llm importing scraping). Everything else is
feature-local: HTTP models in jobs/schemas.py, the row validator next to the
executor that runs it.

Imports nothing from this project.
"""
from dataclasses import dataclass


@dataclass
class Attempt:
    """One generate -> execute -> validate round."""

    code: str
    output: list[dict] | None
    error: str | None          # traceback or validation message
    success: bool
