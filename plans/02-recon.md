# Plan 02 — Recon

**Goal:** `recon(url) -> Recon` — load a page with Playwright and return a
*compact* structural summary. This module never calls the LLM (`rules.md` §B6).

**Owner:** `backend-engineer` designs the reduction; `script-writer` implements.

## Files

```
backend/recon.py
tests/fixtures/shop.html
tests/test_recon.py
```

## The contract

```python
@dataclass
class Recon:
    url: str
    title: str
    elements: list[dict]      # {tag, id, class, testid, aria, text, href}
    search: dict | None       # {selector, submit: "enter" | "<button selector>"}
    pagination: dict | None   # {kind, selector}
```

## Steps

1. **Load.** Headless chromium, `page.goto(url, wait_until="networkidle",
   timeout=30_000)`. Always close the browser in a `finally`.
2. **Reduce the DOM.** One `page.evaluate` that walks the tree and keeps, per
   element: `tag`, `id`, `class` (first 3 tokens), `data-testid`,
   `aria-label`, `href`, and visible text truncated to 80 chars.
   Drop entirely: `script`, `style`, `svg`, `noscript`, `head`, elements with
   no text and no href and no stable attribute.
   Cap the result at ~400 elements — keep the ones with stable attributes first.
   `# ponytail: fixed cap; make it token-budget-aware if pages get truncated badly`
3. **Detect search.** `input[type=search]`, `input[name*=search|q|query]`,
   `[role=searchbox]`, or an input inside a `<form>`. Submit mechanism: a
   sibling/descendant `button[type=submit]` selector if one exists, else
   `"enter"`.
4. **Detect pagination**, first match wins:
   - `next_link` — an `<a>`/`<button>` whose text or aria-label matches
     `/next|→|›|more/i`
   - `numbered` — a container with ≥3 links whose text is a bare integer
   - `infinite_scroll` — a `[data-infinite]`, an IntersectionObserver sentinel,
     or nothing found but the page grew on scroll
5. **Return `Recon`.** Prefer `data-testid` / `aria-label` / `id` in every
   selector you emit over generated class names (`rules.md` §C13).

## Check (`test-engineer`)

Build `tests/fixtures/shop.html` — a search input with a submit button, 10
product cards with `data-testid`, and a "Next →" link. Load it via
`page.set_content(...)` (no network, `rules.md` §E23).

Assert:
- `search["submit"]` is the button selector, not `"enter"`
- `pagination["kind"] == "next_link"`
- every product card appears in `elements`
- `"<script>" not in json.dumps(recon.elements)` — the reduction actually ran
- `len(json.dumps(asdict(recon))) < 40_000` — compactness is a *tested*
  property, not an aspiration

## Out of scope

Login walls, iframes, shadow DOM, screenshots.
