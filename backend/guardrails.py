"""Three rails around the parts of this system nobody in this repo wrote: the
URL a user points us at, the Python an LLM wrote, and the rows that Python
scrapes off somebody else's page.

All three are deterministic -- an `ast` walk, an `ipaddress` check and a
handful of regexes, not a second model asked to judge the first. A model-based
rail costs an LLM call per job, adds its latency to every job, and is wrong
sometimes; a syntax tree is free, instant, and wrong never. (This is why nemoguardrails is not a dependency here:
its rails are LLM calls plus a colang dialog runtime, and this app has no
dialog -- the risky artifact is a Python file. See README "Guardrails".)

The first two rails are about safety; the third is about truth. A script can
be perfectly harmless and still return `{"name": "Load More"}` or an NMLS id
with two licence numbers run together, and schema validation waves both
through -- they are strings, and the schema asked for strings. That row then
becomes a person in the database. `check_officer` is where a row stops being
trusted just because it parsed.

The script rail bounds what a generated script can reach on *this machine*. It
cannot bound what the script sends to the site it is already allowed to browse
-- `page.goto` with data in the query string is a channel no static check can
close. Network egress is a sandbox's job, not a parser's.
# ponytail: static AST only. If exfiltration through the browser itself ever
# matters, that is a network-namespaced container, not a longer ban list.

Imports stdlib and config only, so any module may import it.
"""
from __future__ import annotations

import ast
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse

from backend import config

# Names a page-scraping function never needs, and every sandbox escape starts
# from. Banned wherever they appear, not just when called: `f = open` then
# `f(...)` is the same reach with one more line.
BANNED_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
})

# Pure computation, and nothing else: no filesystem, no network, no process.
# The reach this rail exists to stop is `os`, `sys`, `subprocess`, `socket`,
# `shutil`, `pathlib` -- not text parsing. The model writes `import re`
# reflexively however loudly the prompt forbids it, and blocking it spent a
# repair attempt to buy no safety at all.
# ponytail: a name list, so `import urllib` (no `.parse`) is blocked too. A
# runaway regex is the subprocess timeout's problem, as it already was.
SAFE_IMPORTS = frozenset({
    "re", "json", "math", "string", "decimal", "datetime", "html",
    "itertools", "collections", "unicodedata", "textwrap", "urllib.parse",
})

# Only these may sit at module level. The generated code is pasted into the
# harness body (executor.py), so anything else there runs before `run(page)` is
# ever called -- outside the schema validation, outside the result capture.
_TOP_LEVEL = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign,
              ast.Import, ast.ImportFrom)


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def check_script(code: str) -> str | None:
    """Why this generated script must not run, or None if it may.

    The message is written to be read by the model: it goes back into the
    repair prompt as the attempt's error, so a blocked script self-heals on the
    next attempt instead of dead-ending the job (executor.py returns it as a
    normal failed Attempt).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"blocked by guardrails: the script does not parse ({e})"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Every alias, not just the first -- `import re, os` is one node.
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                names = ["." * node.level] if node.level else [node.module or ""]
            if bad := [n for n in names if n not in SAFE_IMPORTS]:
                return (
                    f"blocked by guardrails: `import {bad[0]}`. A scraping script "
                    "reads the page and nothing else -- no filesystem, no network, "
                    "no process. For parsing you may import: "
                    f"{', '.join(sorted(SAFE_IMPORTS))}."
                )
        if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            return (
                f"blocked by guardrails: `{node.id}` is not available to a scraping "
                "script. Read the page through `page`, never the machine it runs on."
            )
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return (
                f"blocked by guardrails: `.{node.attr}` -- dunder attributes are the "
                "way out of a sandbox and no selector needs one."
            )

    for node in tree.body:
        if not isinstance(node, _TOP_LEVEL) and not _is_docstring(node):
            return (
                f"blocked by guardrails: {type(node).__name__} at module level. Only "
                "`def run(page)`, helper functions and constants are allowed -- "
                "module-level statements run outside the harness."
            )

    return None


def check_url(url: str) -> str | None:
    """Why this URL must not be fetched, or None if it may.

    The scheme is already Pydantic's job (jobs/schemas.py); this is the other
    half: a URL naming this machine or the private network turns "scrape a
    page for me" into a request from inside the trust boundary -- a cloud
    metadata endpoint, an admin port bound to localhost.

    Unresolvable hosts pass. Blocking them here would report a DNS failure as
    a validation error; recon fails on it a second later with the real reason.

    # ponytail: resolve-then-check, so a name that resolves again differently
    # (DNS rebinding) is not covered. The fix is egress control, not a retry.
    """
    if config.ALLOW_PRIVATE_URLS:           # local fixture sites, dev only
        return None

    host = urlparse(url).hostname
    if not host:
        return "url has no host"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return None

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:                  # not an address we can judge
            continue
        if not ip.is_global:
            return (
                f"{host} resolves to {ip}, which is not a public address. "
                "Set ALLOW_PRIVATE_URLS=1 to scrape a local or internal site."
            )
    return None


# --- the third rail: a scraped row claiming to be a person ------------------
# A real NMLS id is a registry sequence number. The highest anyone has been
# issued is around 2.8 million, so seven digits is the whole live range today
# and every one of the 67 companies in the broker sheet fits it.
#
# Calibrated against real scrapes, not chosen on paper. Eight was the first
# guess and it let `15338206` through -- a genuine seven-digit id with a stray
# digit run onto the end, indistinguishable from a real id by shape alone until
# the range is tight. Fourteen digits is the same bug at full volume: a
# directory that prints "NMLS# 943184 / CA DRE# 02079631" hands a script that
# strips non-digits a number that belongs to nobody.
#
# ponytail: raise to 8 when the registry actually issues 8-digit ids -- around
# id 10,000,000, which is years of headroom. The cost of being late is a
# rejected row and one repair attempt; the cost of being loose is a fabricated
# licence number stored as fact.
_NMLS = re.compile(r"\A[0-9]{1,7}\Z")

# Deliberately loose. This rail is here to catch "Director of Operations" in
# the email column, not to adjudicate RFC 5322.
_EMAIL = re.compile(r"\A[^@\s]+@[^@\s.]+\.[^@\s]+\Z")

_HAS_LETTER = re.compile(r"[^\W\d_]")

# Text that is a control, a heading or a cookie banner, not a person. Matched
# against the whole name, never a substring: "Moreno" contains "more", and a
# rail that eats a real surname is worse than the row it was meant to stop.
NOT_A_NAME = frozenset({
    "load more", "show more", "view more", "see more", "read more", "more",
    "next", "previous", "prev", "back", "close", "menu", "search", "filter",
    "our team", "the team", "meet our team", "team", "our staff", "staff",
    "loan officers", "loan officer", "find a loan officer", "our people",
    "contact us", "contact", "about us", "about", "home", "apply now", "apply",
    "learn more", "get started", "view profile", "view bio", "email me",
    "accept all cookies", "accept", "n/a", "na", "none", "null", "undefined",
    "name", "unknown", "tbd", "test",
})

# A name longer than this is a paragraph that landed in the wrong field --
# a bio, an address block, a whole card's inner_text().
MAX_NAME_CHARS = 120


def check_officer(row: dict[str, Any]) -> str | None:
    """Why this scraped row is not a loan officer, or None if it may be kept.

    Rejects the whole row rather than repairing a field, and that is the point.
    A fourteen-digit NMLS id does not mean one bad value -- it means the script
    read the wrong container for that card, so the address and the phone beside
    it are mis-parsed too. Half a person is worse than no person: it lands in
    the database looking like a fact.

    The caller drops what this rejects and, when it rejects most of a run,
    records that on the company -- which is what makes the next "Generate
    scripts" pass rewrite that site's script rather than skip it
    (companies/runner.py). A bad harvest self-heals the same way a bad script
    does; that loop is the product (CLAUDE.md 2).

    Every check is on the *shape* of a value, never on whether a real person
    has that name. Judging plausibility is a model's job and this is a rail.
    """
    name = _clean(row.get("name"))
    nmls = _clean(row.get("nmls_id"))

    if not name and not nmls:
        return "no name and no NMLS id -- the row identifies nobody"

    if name:
        if len(name) > MAX_NAME_CHARS:
            return (f"name is {len(name)} characters -- that is a bio or an "
                    f"address block, not a name: {name[:60]!r}...")
        if not _HAS_LETTER.search(name):
            return f"name has no letters in it: {name!r}"
        if name.casefold() in NOT_A_NAME:
            return f"{name!r} is a button or a heading, not a person"

    if nmls and not _NMLS.match(nmls):
        return (f"{nmls!r} is not an NMLS id (expected 1-8 digits). The script "
                "read the wrong element, so the rest of this row is suspect too.")

    email = _clean(row.get("email"))
    if email and not _EMAIL.match(email):
        return f"{email!r} is not an email address"

    phone = _clean(row.get("phone"))
    if phone and not 7 <= sum(c.isdigit() for c in phone) <= 15:
        return f"{phone!r} is not a phone number -- wrong number of digits"

    return None


def _clean(value: Any) -> str:
    """The same normalisation companies/db.py applies before storing a value,
    so the rail judges exactly the text that would land in the row -- including
    the &nbsp; that real pages are full of."""
    return "" if value is None else " ".join(str(value).split())
