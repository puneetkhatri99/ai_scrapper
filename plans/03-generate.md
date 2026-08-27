# Plan 03 — Generate (the LLM layer)

**Goal:** turn `(Recon, json_schema, prompt, prior_attempt?)` into Python source
for `def run(page) -> list[dict]`. This module never touches Playwright
(`rules.md` §B6).

**Owner:** `backend-engineer`. This is the highest-leverage module — do not
delegate the prompt design.

## Files

```
backend/generate.py
backend/prompts.py       # the frozen system prompt lives here alone
tests/test_generate.py
```

## API surface (per the SDK)

```python
client = anthropic.Anthropic()            # zero-arg; SDK resolves credentials

with client.messages.stream(
    model="claude-opus-5",
    max_tokens=16000,
    thinking={"type": "adaptive"},
    output_config={"effort": "high"},
    system=[{"type": "text", "text": SYSTEM,
             "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": user_block}],
) as stream:
    msg = stream.get_final_message()
```

Non-negotiables from `rules.md` §C:
- `claude-opus-5`, never downgraded.
- `thinking={"type": "adaptive"}` — **no `budget_tokens`**, it 400s on Opus 5.
- **Streaming** — long output, non-streaming risks an HTTP timeout.
- Frozen system prompt with `cache_control`; everything volatile after it.

## Prompt layout (cache-critical)

```
system  [CACHED]  ← contract, rules, few-shot skeleton. Byte-identical every call.
user              ← recon summary
                  ← json_schema
                  ← user prompt
                  ← prior attempt code + error   (repair calls only)
```

Nothing volatile above the breakpoint. No timestamps, no UUIDs,
`json.dumps(..., sort_keys=True)` everywhere (`rules.md` §C12).

## The system prompt says

- You write **exactly one function**: `def run(page) -> list[dict]`.
- `page` is an open Playwright sync `Page`, already navigated to the target URL.
- No imports, no browser launch, no `print`, no validation, no `input()`.
- Return a list of flat dicts matching the given JSON Schema keys.
- Prefer `get_by_test_id` / `get_by_role` / `get_by_label` over CSS class
  selectors.
- Wait explicitly (`page.wait_for_selector`, `expect_...`), never `sleep`.
- Respect the requested item count; stop paginating once you have it.
- Output the function in a single ```python fence and nothing else.

## Steps

1. `render_recon(recon) -> str` — compact text, not JSON blobs of raw HTML.
2. `build_user_block(recon, schema, prompt, prior)` — the four sections above.
3. `generate(...) -> str` — stream, take the final message, extract the fenced
   block, `ast.parse` it, and confirm a top-level `def run` with one parameter.
   If it does not parse, raise — do not hand broken source to the executor.
4. **Errors:** catch `RateLimitError`, `APIStatusError`, `APIConnectionError`
   as a most-specific-first chain (`rules.md` §D20). Let the SDK's own retry
   handle the transient cases; do not add a second retry layer.

## Check (`test-engineer`)

- Stub the client (`rules.md` §E22). Feed a canned fenced response → assert
  `generate` returns source that `ast.parse`s with a top-level `run(page)`.
- Feed a response with prose and no fence → assert it raises, loudly.
- Feed a response whose code has a syntax error → assert it raises.
- **Cache test:** call `generate` twice with different user blocks and assert
  the `system` argument passed to the client is byte-identical both times.
  That is the invariant that keeps `cache_read_input_tokens > 0` in production.
- Assert the request kwargs contain no `budget_tokens` key.

## Out of scope

Structured outputs, tool use, multi-turn conversation. One call in, one script
out.
