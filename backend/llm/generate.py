"""Recon + schema + prompt -> Python source for `def run(page) -> list[dict]`.

The only module that talks to the LLM. Never imports playwright, db, or
subprocess (architecture.md 2).

Provider: Google Gemini, via its OpenAI-compatible /chat/completions endpoint.
The Anthropic path it replaced is kept commented at the bottom of this file --
everything above it (prompt assembly, code extraction) is provider-agnostic
and shared by both.

Two models, one job: GEMINI_MODEL writes the first script from recon (the
hard, expensive call), GEMINI_REPAIR_MODEL rewrites it from a real traceback
on attempts 2..3 (the cheap, narrow one). Both are env-driven, so changing
either needs no code change.

The key is read from GEMINI_API_KEY (or GOOGLE_API_KEY) at call time and never
logged or persisted (rules.md A3).
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
from typing import TYPE_CHECKING

import httpx

from backend.config import LLM_TIMEOUT, MAX_ERROR_CHARS, MAX_OUTPUT_TOKENS
from backend.contracts import Attempt
from backend.llm.prompts import SYSTEM

if TYPE_CHECKING:                       # type only -- keeps playwright out of
    from backend.scraping.recon import Recon     # this module at runtime (architecture.md 2)

log = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

# Writing a scraper from a DOM snapshot is the reasoning-heavy half; patching
# one from its own traceback is not. Splitting them is the whole point of
# having two model names here.
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
# ponytail: flash-lite repairs. If attempt 2/3 starts failing where the first
# attempt nearly worked, raise this to GEMINI_MODEL and the loop is back to
# one model.
REPAIR_MODEL = os.getenv("GEMINI_REPAIR_MODEL", "gemini-3.1-flash-lite")

# Statuses that mean "not this model, right now" rather than "not ever": 503 is
# Gemini shedding load, 429 is a per-model quota. Both are survivable by asking
# a smaller model instead. A 400/401/404 is not, and must still fail loudly.
UNAVAILABLE = (429, 503)

# Built once and sent first, byte-identical every call. Gemini caches the
# prompt prefix implicitly, so a stable prefix is still what makes a repair
# call cheap -- the same reason the Anthropic path pinned cache_control here.
SYSTEM_MESSAGE = {"role": "system", "content": SYSTEM}

_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def _attr(e: dict) -> str:
    """The most durable identifier this element has (rules.md C13)."""
    if e.get("testid"):
        return f'[data-testid="{e["testid"]}"]'
    if e.get("id"):
        return f'#{e["id"]}'
    if e.get("aria"):
        return f'[aria-label="{e["aria"]}"]'
    return f'.{e["class"].split()[0]}' if e.get("class") else ""


def _line(e: dict, indent: str) -> str:
    parts = [e["tag"] + _attr(e)]
    if e.get("text"):
        parts.append(f'"{e["text"]}"')
    if e.get("href"):
        parts.append(f'-> {e["href"]}')
    return indent + " ".join(parts)


def render_recon(recon: Recon) -> str:
    """Compact text, one line per element. Never raw HTML (rules.md C13)."""
    lines = [f"url: {recon.url}", f"title: {recon.title}", "", "elements:"]
    lines += [_line(e, "  ") for e in recon.elements]

    lines.append("")
    lines.append(
        f"search: input {recon.search['selector']}, submit via {recon.search['submit']}"
        if recon.search
        else "search: none detected"
    )
    lines.append(
        f"pagination: {recon.pagination['kind']} at {recon.pagination['selector']}"
        if recon.pagination
        else "pagination: none detected"
    )

    # recon.py followed one card so the model can see what is behind them.
    # Its siblings have the same structure, so these selectors generalise.
    if recon.detail is not None:
        lines += ["", f"detail page behind one card ({recon.detail.url}):"]
        lines += [_line(e, "    ") for e in recon.detail.elements]

    return "\n".join(lines)


def build_user_block(
    recon: Recon, json_schema: dict, prompt: str, prior: Attempt | None = None
) -> str:
    """Everything volatile, in one block after the cache breakpoint."""
    parts = [
        "# Page snapshot\n\n" + render_recon(recon),
        # sort_keys: same schema always renders the same way (rules.md C12).
        "# JSON Schema the returned dicts must match\n\n```json\n"
        + json.dumps(json_schema, sort_keys=True, indent=2)
        + "\n```",
        "# What the user wants extracted\n\n" + prompt,
    ]
    if prior is not None:
        parts.append(
            "# Your previous attempt failed\n\n```python\n"
            + prior.code
            + "\n```\n\nIt produced this error:\n\n```\n"
            + (prior.error or "empty result")
            + "\n```\n\nFix it. Change the selector or the strategy, not just the timeout."
        )
    return "\n\n---\n\n".join(parts)


def _extract_code(text: str) -> str:
    """Pull the fenced block and prove it is a usable `run(page)`.

    Broken source must never reach executor.py -- a syntax error there costs a
    subprocess launch and a wasted retry to discover.
    """
    m = _FENCE.search(text)
    if not m:
        raise ValueError(f"model returned no ```python fence, got: {text[:500]!r}")
    code = m.group(1).strip()

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"generated code does not parse ({e}):\n{code}") from e

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            n = len(node.args.posonlyargs) + len(node.args.args)
            if n != 1:
                raise ValueError(f"run() takes {n} positional args, expected 1:\n{code}")
            return code

    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    raise ValueError(f"no top-level `def run`, found {names}:\n{code}")


def _api_key() -> str:
    """Read at call time, never at import, never logged (rules.md A3)."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            "no Gemini credentials: export GEMINI_API_KEY (or GOOGLE_API_KEY) "
            "before starting the server"
        )
    return key


def generate(
    recon: Recon,
    json_schema: dict,
    prompt: str,
    prior: Attempt | None = None,
    *,
    client: httpx.Client | None = None,
) -> str:
    """One call in, one script out. Raises if the model returns anything else.

    # ponytail: at most one POST per model, no backoff and no streaming. A
    # 503/429 steps down to the next model immediately instead of sleeping --
    # if both are busy the job fails with the real message rather than hiding
    # behind a retry nobody can see. Add a backoff only if stepping down stops
    # being enough.
    """
    # A repair has a prior attempt attached, a first generation does not --
    # that is the whole model split. REPAIR_MODEL then trails as the fallback:
    # when the writer is overloaded, a smaller model writes a worse script,
    # which still beats failing the job outright.
    models = [REPAIR_MODEL] if prior is not None else [MODEL, REPAIR_MODEL]
    payload = {
        "model": models[0],
        "max_completion_tokens": MAX_OUTPUT_TOKENS,
        "messages": [
            SYSTEM_MESSAGE,             # frozen prefix, first, every call
            {"role": "user",
             "content": build_user_block(recon, json_schema, prompt, prior)},
        ],
    }

    http = client or httpx.Client(timeout=LLM_TIMEOUT)
    try:
        for i, model in enumerate(models):
            payload["model"] = model
            resp = http.post(
                API_URL,
                json=payload,
                headers={"authorization": f"Bearer {_api_key()}"},
            )
            if resp.status_code not in UNAVAILABLE or i == len(models) - 1:
                break                   # served, dead, or nothing left to try
            log.warning("generate model=%s got %s, falling back to %s",
                        model, resp.status_code, models[i + 1])
    finally:
        if client is None:              # only close what we opened
            http.close()

    if resp.is_error:
        # The body is where Gemini says *why* (unknown model, quota of 0 on
        # the free tier, bad key). Dropping it is how a 400 or a 429 becomes an
        # unreadable job failure.
        raise httpx.HTTPStatusError(
            f"Gemini returned {resp.status_code}: {resp.text[:MAX_ERROR_CHARS]}",
            request=resp.request,
            response=resp,
        )

    body = resp.json()
    choice = body["choices"][0]
    message = choice["message"]

    u = body.get("usage") or {}
    # Cost visibility: cached=0 on a repair call means something volatile
    # leaked into the frozen prefix and every call is paying full price.
    log.info(
        "generate model=%s repair=%s input=%s output=%s cached=%s",
        model, prior is not None,
        u.get("prompt_tokens"), u.get("completion_tokens"),
        (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
    )

    if message.get("refusal"):
        raise ValueError(f"model refused to generate a script: {message['refusal']}")
    if choice.get("finish_reason") == "length":
        raise ValueError(
            f"model hit the {MAX_OUTPUT_TOKENS}-token cap before finishing the script"
        )

    return _extract_code(message.get("content") or "")


# --- the Anthropic path, replaced by the xAI one above ----------------------
#
# Restore by uncommenting this and `import anthropic`, and swapping the two
# `generate` definitions. The system prompt, prompt assembly and code
# extraction above are shared, so nothing else changes.
#
# MODEL = "claude-opus-5"
# SYSTEM_BLOCK = [
#     {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
# ]
#
# def generate(
#     recon: Recon,
#     json_schema: dict,
#     prompt: str,
#     prior: Attempt | None = None,
#     *,
#     client: "anthropic.Anthropic | None" = None,
# ) -> str:
#     """One call in, one script out. Raises if the model returns anything else.
#
#     # ponytail: no try/except around the call -- the SDK already retries
#     # 429/5xx and connection errors, and a chain that only re-raises hides
#     # nothing. retry_loop.py turns a raise into jobs.status=failed.
#     """
#     # Zero-arg: the SDK resolves credentials itself, never us (rules.md A3).
#     client = client or anthropic.Anthropic()
#
#     with client.messages.stream(
#         model=MODEL,
#         max_tokens=MAX_OUTPUT_TOKENS,
#         thinking={"type": "adaptive"},      # no budget_tokens -- 400s on Opus 5
#         output_config={"effort": "high"},
#         system=SYSTEM_BLOCK,
#         messages=[
#             {"role": "user",
#              "content": build_user_block(recon, json_schema, prompt, prior)}
#         ],
#     ) as stream:
#         msg = stream.get_final_message()
#
#     u = msg.usage
#     log.info(
#         "generate model=%s repair=%s input=%s output=%s cache_read=%s cache_write=%s",
#         model, prior is not None, u.input_tokens, u.output_tokens,
#         getattr(u, "cache_read_input_tokens", 0),
#         getattr(u, "cache_creation_input_tokens", 0),
#     )
#
#     if msg.stop_reason == "refusal":
#         raise ValueError(f"model refused to generate a script: {msg.stop_details}")
#
#     return _extract_code("".join(b.text for b in msg.content if b.type == "text"))
