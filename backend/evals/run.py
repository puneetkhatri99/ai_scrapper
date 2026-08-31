"""Extraction evals: not "did the pipeline run" but "is the data right".

    .venv/bin/python -m backend.evals.run              # all cases
    .venv/bin/python -m backend.evals.run detail-pages # one
    .venv/bin/python -m backend.evals.run -v           # print the winning script too

This spends real LLM calls, so it is deliberately NOT a pytest file -- the
suite must never bill anyone (rules.md E22). It runs the same three steps
jobs/retry_loop.py runs, in the same order, with the same attempt cap, but
without the database: an eval measures generation quality, and a cache hit
would measure nothing at all.

The pass bar is exact. A scraper that returns five of six products, or the
right products with "$129.00" where the schema said number, is not "mostly
fine" -- it is the failure this project exists to catch before a user does.
"""
import argparse
import functools
import http.server
import statistics
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from backend.config import MAX_ATTEMPTS
from backend.evals.cases import CASES
from backend.llm import generate
from backend.scraping import executor, recon

SITES = Path(__file__).parent / "sites"


def serve(directory: Path):
    """The eval sites, on a loopback port. Same reason the tests do it."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass                            # the eval table is the output

    handler = functools.partial(Quiet, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}/", srv.shutdown


def _norm(row: dict, keys) -> tuple:
    """A row reduced to what the case actually compares.

    Extra keys are ignored -- the schema validator already ruled on shape.
    Numbers compare as rounded floats so 129 and 129.0 are the same answer.

    Strings are whitespace-collapsed rather than merely stripped, because that
    is what the app itself stores (companies/db._text) and real pages are full
    of &nbsp;. Comparing the raw string would fail a scraper for a character
    the pipeline already handles -- the eval would be measuring the fixture.

    Empty string and None are the same answer: "the site does not show this".
    A model asked for an optional field returns one or the other more or less
    at random, and no case has ever wanted to tell them apart.
    """
    out = []
    for k in keys:
        v = row.get(k)
        if isinstance(v, str):
            v = " ".join(v.split()) or None
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            v = round(float(v), 2)
        out.append((k, v))
    return tuple(out)


def score(got: list[dict], case) -> tuple[int, list, list]:
    """(matched, missing, extra) as multisets -- order is not part of correct."""
    keys = case.compared()
    want = Counter(_norm(r, keys) for r in case.expect)
    have = Counter(_norm(r, keys) for r in got)
    matched = sum((want & have).values())
    return matched, list((want - have).elements()), list((have - want).elements())


def run_case(case, base: str) -> dict:
    """recon -> generate -> execute -> repair, exactly as retry_loop drives it."""
    url = base + case.page
    started = time.monotonic()
    out = {"case": case, "attempts": 0, "blocked": 0, "code": None, "error": None}

    try:
        rec = recon.recon(url)
    except Exception as e:                      # noqa: BLE001 -- reported, not swallowed
        out.update(outcome="error", error=f"recon: {e}", secs=time.monotonic() - started)
        return out

    prior = None
    for n in range(1, MAX_ATTEMPTS + 1):
        out["attempts"] = n
        try:
            code = generate.generate(rec, case.schema, case.prompt, prior)
        except Exception as e:                  # noqa: BLE001
            out.update(outcome="error", error=f"generate: {e}",
                       secs=time.monotonic() - started)
            return out

        att = executor.execute(code, url, case.schema)
        out["code"] = att.code
        # A rail firing on a real model's output is the guardrails' own eval:
        # every block here is either a caught escape or a false positive that
        # cost an attempt. Either way it belongs in the report.
        if att.error and att.error.startswith("blocked by guardrails"):
            out["blocked"] += 1
        if att.success:
            matched, missing, extra = score(att.output, case)
            out.update(
                outcome="ok" if not missing and not extra else "wrong",
                matched=matched, missing=missing, extra=extra,
                # What the data rail would have made of a real model's output.
                # The schema said these rows are fine; this asks whether they
                # are true. On a passing case every rejection is a false
                # positive, and a false positive here is 67 empty companies.
                rejected=[r for row in att.output
                          if (r := case.rail(row)) is not None] if case.rail else [],
                secs=time.monotonic() - started,
            )
            return out
        prior = att

    out.update(outcome="failed", error=prior.error, secs=time.monotonic() - started)
    return out


def report(results: list[dict], verbose: bool) -> int:
    print(f"\n{'case':<14} {'outcome':<8} {'att':>3} {'rows':>7} {'secs':>6}")
    print("-" * 44)
    for r in results:
        rows = (f"{r['matched']}/{len(r['case'].expect)}"
                if r["outcome"] in ("ok", "wrong") else "-")
        print(f"{r['case'].name:<14} {r['outcome']:<8} {r['attempts']:>3} "
              f"{rows:>7} {r['secs']:>6.1f}")

    for r in results:
        if r["outcome"] == "ok":
            continue
        print(f"\n--- {r['case'].name}: {r['case'].tests}")
        for label in ("missing", "extra"):
            for row in r.get(label) or []:
                print(f"    {label:<8} {dict(row)}")
        if r["error"]:
            print(f"    error    {r['error'][:600]}")
        if verbose and r["code"]:
            print("\n" + r["code"])

    if verbose:
        for r in results:
            if r["outcome"] == "ok" and r["code"]:
                print(f"\n--- {r['case'].name} (passing script)\n{r['code']}")

    ok = [r for r in results if r["outcome"] == "ok"]
    blocked = sum(r["blocked"] for r in results)
    rejected = [(r["case"].name, reason)
                for r in results for reason in r.get("rejected") or []]
    attempts = [r["attempts"] for r in results]
    print(f"\n{len(ok)}/{len(results)} correct, "
          f"{statistics.mean(attempts):.1f} attempts/case, "
          f"{sum(r['secs'] for r in results):.0f}s total")
    if blocked:
        # Not necessarily bad -- but never ignore it. A block on this corpus is
        # a false positive, because none of these cases asks for a file or an
        # import; the rail's own corpus is tests/test_guardrails.py.
        print(f"guardrails blocked {blocked} generated script(s) -- "
              f"check tests/test_guardrails.py::ALLOWED for a false positive")
    if rejected:
        # On a case that scored ok, every one of these is a rail eating a real
        # person -- the failure mode that turns a working scraper into an empty
        # company. Loud, and named, so it cannot be scrolled past.
        print(f"\nofficer rail rejected {len(rejected)} scraped row(s):")
        for name, reason in rejected[:10]:
            print(f"    {name:<14} {reason}")
        print("    ^ on a passing case these are false positives -- "
              "add them to tests/test_guardrails.py::KEEP")
    return 0 if len(ok) == len(results) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*", help="case names to run (default: all)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print the generated script for every case")
    args = ap.parse_args()

    cases = [c for c in CASES if not args.names or c.name in args.names]
    if not cases:
        print(f"no such case. have: {', '.join(c.name for c in CASES)}", file=sys.stderr)
        return 2

    base, stop = serve(SITES)
    try:
        results = []
        for case in cases:
            print(f"running {case.name} ...", flush=True)
            results.append(run_case(case, base))
    finally:
        stop()
    return report(results, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
