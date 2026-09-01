"""Page load + DOM reduction. Never calls the LLM (rules.md B6).

One `page.evaluate` does the whole job: reduce the tree, pick a search box,
pick a pagination pattern. Doing it in the browser means one round trip and no
raw HTML ever crosses into Python (rules.md C13).
"""
import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

from backend.config import PROXY, RECON_SETTLE, RECON_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)


@dataclass
class Recon:
    url: str
    title: str
    elements: list[dict]      # {tag, id, class, testid, aria, text, href}
    search: dict | None       # {selector, submit: "enter" | "<button selector>"}
    pagination: dict | None   # {kind, selector}
    detail: "Recon | None" = None   # one card's target page, see _card_href


# ponytail: fixed 400-element cap; make it token-budget-aware if pages get
# truncated badly. Also: infinite scroll is detected by sentinel attribute
# only -- add a scroll-and-measure probe if sentinel-less sites show up.
_JS = r"""
(MAX) => {
  const DROP = new Set(['SCRIPT','STYLE','SVG','NOSCRIPT','HEAD','META','LINK','TITLE','BASE']);
  const INTERACTIVE = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA','FORM']);
  const esc = s => String(s).replace(/"/g, '\\"');
  const stable = el =>
    el.getAttribute('data-testid') || el.id || el.getAttribute('aria-label');

  // Stable attributes first -- LLMs write more durable selectors from them.
  const sel = el => {
    const t = el.getAttribute('data-testid');
    if (t) return `[data-testid="${esc(t)}"]`;
    if (el.id) return '#' + CSS.escape(el.id);
    const a = el.getAttribute('aria-label');
    if (a) return `[aria-label="${esc(a)}"]`;
    const tag = el.tagName.toLowerCase();
    const n = el.getAttribute('name');
    if (n) return `${tag}[name="${esc(n)}"]`;
    const ty = el.getAttribute('type');
    if (ty) return `${tag}[type="${esc(ty)}"]`;
    const c = (el.getAttribute('class') || '').trim().split(/\s+/)[0];
    return c ? `${tag}.${CSS.escape(c)}` : tag;
  };

  // Own text nodes only -- subtree text would repeat on every ancestor.
  const ownText = el => {
    let s = '';
    for (const n of el.childNodes) if (n.nodeType === 3) s += n.nodeValue + ' ';
    return s.replace(/\s+/g, ' ').trim().slice(0, 80);
  };

  const kept = [];
  for (const el of document.querySelectorAll('body *')) {
    if (DROP.has(el.tagName) || el.closest('svg')) continue;
    const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean);
    const rec = {
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      class: cls.slice(0, 3).join(' ') || null,
      testid: el.getAttribute('data-testid'),
      aria: el.getAttribute('aria-label'),
      text: ownText(el),
      href: el.getAttribute('href'),
    };
    if (!rec.text && !rec.href && !stable(el) && !INTERACTIVE.has(el.tagName)) continue;
    kept.push({el, rec});
  }
  const ranked = kept.filter(k => stable(k.el)).concat(kept.filter(k => !stable(k.el)));
  const elements = ranked.slice(0, MAX).map(k => k.rec);

  let search = null;
  const input =
    document.querySelector('input[type="search"], [role="searchbox"], ' +
      'input[name="q"], input[name*="search" i], input[name*="query" i], ' +
      'input[placeholder*="search" i]') ||
    document.querySelector('form input[type="text"], form input:not([type])');
  if (input) {
    const btn = (input.closest('form') || document)
      .querySelector('button[type="submit"], input[type="submit"], button');
    search = {selector: sel(input), submit: btn ? sel(btn) : 'enter'};
  }

  let pagination = null;
  // Anchored and length-bounded: a real pager's whole label is the word.
  // Unanchored, /more/ made "Learn more about this provider" the next button
  // on a real site, and every generated script then clicked the wrong link.
  const nextish = s => {
    const t = (s || '').trim();
    return t.length <= 24 &&
      (/^(next|more|load more|show more|older)\b/i.test(t) || /^[→›»]/.test(t));
  };
  const next = [...document.querySelectorAll('a, button')].find(e =>
    nextish(e.textContent) || nextish(e.getAttribute('aria-label')));
  if (next) pagination = {kind: 'next_link', selector: sel(next)};
  if (!pagination) {
    for (const c of document.querySelectorAll('body *')) {
      const n = [...c.children].filter(k =>
        (k.tagName === 'A' || k.tagName === 'BUTTON') && /^\d+$/.test((k.textContent || '').trim()));
      if (n.length >= 3) { pagination = {kind: 'numbered', selector: sel(c)}; break; }
    }
  }
  if (!pagination) {
    const s = document.querySelector('[data-infinite], [data-testid*="sentinel" i], [class*="infinite" i]');
    if (s) pagination = {kind: 'infinite_scroll', selector: sel(s)};
  }

  return {title: document.title, elements, search, pagination};
}
"""


def reduce_page(page, url: str, limit: int = 400) -> Recon:
    """Reduce an already-loaded page. Split out so tests can use set_content."""
    d = page.evaluate(_JS, limit)
    return Recon(url=url, title=d["title"], **{k: d[k] for k in ("elements", "search", "pagination")})


def _card_href(elements: list[dict], base: str) -> str | None:
    """One card's link, when the page is a list of them -- else None.

    Cards are the biggest group of links sharing a shape: same first path
    segment and same depth. `/p/1` and `/p/2` group; `/about` never joins
    them. Three is the floor, so a lone "Terms" link is not a card.

    # ponytail: shape by first segment + depth, first member wins. Rank by
    # position on the page if a nav menu ever out-groups the real cards.
    """
    home = urlparse(base)
    groups: dict[tuple, list[str]] = {}
    for e in elements:
        href = e.get("href")
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        u = urlparse(urljoin(base, href))
        seg = [s for s in u.path.split("/") if s]
        # Same site only, and never the listing itself.
        if u.netloc != home.netloc or not seg or u.path == home.path:
            continue
        groups.setdefault((len(seg), seg[0]), []).append(u.geturl())

    best = max(groups.values(), key=len, default=[])
    return best[0] if len(best) >= 3 else None


def recon(url: str, timeout: int = RECON_TIMEOUT) -> Recon:
    """Load `url` and reduce it. Raises on an unreachable or refusing site --
    retry_loop.py turns that into a `failed` job the user can read."""
    with sync_playwright() as p:
        browser = p.chromium.launch(proxy=PROXY)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            # domcontentloaded, not networkidle: a page with ad frames, chat
            # widgets or polling never goes idle, and waiting for something that
            # never happens failed sites that had finished rendering in a second.
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            # goto only raises on transport failure; a 403 page loads fine and
            # would otherwise reach the LLM as a "please enable JavaScript" wall.
            if resp is not None and resp.status >= 400:
                blocked = " (blocked -- bot protection or auth wall)" if resp.status in (401, 403, 429) else ""
                raise RuntimeError(f"{url} returned HTTP {resp.status}{blocked}")
            # Give a client-rendered list its chance to appear, then reduce
            # whatever is there. Timing out here is the normal case, not an error.
            try:
                page.wait_for_load_state("networkidle", timeout=RECON_SETTLE * 1000)
            except Exception:                             # noqa: BLE001
                pass
            entry = reduce_page(page, url)

            # Follow one card. When the fields the user asked for live on the
            # detail pages rather than the cards, this snapshot is the only DOM
            # the model ever sees for them -- without it, it guesses those
            # selectors blind and the repair loop has nothing to correct from.
            # Best effort: a dead card link must not fail the whole job.
            card = _card_href(entry.elements, url)
            if card:
                try:
                    page.goto(card, wait_until="domcontentloaded",
                              timeout=timeout * 1000)
                    entry.detail = reduce_page(page, card, limit=150)
                except Exception as e:                    # noqa: BLE001
                    log.warning("detail recon of %s failed: %s", card, e)
            return entry
        finally:
            browser.close()
