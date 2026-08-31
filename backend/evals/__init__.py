"""Extraction evals: not "did the pipeline run" but "is the data right".

    .venv/bin/python -m backend.evals.run

cases.py  a local page, a prompt, a schema, and the exact rows that are correct
run.py    recon -> generate -> execute -> repair, then score against `expect`
sites/    the pages, served from loopback so no eval depends on a third party

Inside the package but not part of the app: nothing imports this at runtime,
and it is the one place that spends real LLM money, which is why it is not
pytest (rules.md E22).

Being inside buys two machine-checked guarantees, in the same import table that
governs every other module. An eval may not name the database, and it may not
import `jobs/retry_loop.py`. Both are the same worry: the real loop replays a
saved script when the url, prompt and schema match, and an eval that did that
would be scoring the cache instead of the model -- silently, and in the
flattering direction.
"""
