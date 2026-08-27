"""Page load + DOM reduction. Never calls the LLM (rules.md B6).

One `page.evaluate` does the whole job: reduce the tree, pick a search box,
pick a pagination pattern. Doing it in the browser means one round trip and no
raw HTML ever crosses into Python (rules.md C13).
"""
from dataclasses import dataclass

from playwright.sync_api import sync_playwright

from backend.config import RECON_TIMEOUT


@dataclass
class Recon:
    url: str
    title: str
    elements: list[dict]      # {tag, id, class, testid, aria, text, href}
    search: dict | None       # {selector, submit: "enter" | "<button selector>"}
    pagination: dict | None   # {kind, selector}


# ponytail: fixed 400-element cap; make it token-budget-aware if pages get
# truncated badly. Also: infinite scroll is detected by sentinel attribute
# only -- add a scroll-and-measure probe if sentinel-less sites show up.
_JS = r"""
() => {
  const MAX = 400;
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
  const next = [...document.querySelectorAll('a, button')].find(e =>
    /next|→|›|»|more/i.test((e.textContent || '') + ' ' + (e.getAttribute('aria-label') || '')));
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


def reduce_page(page, url: str) -> Recon:
    """Reduce an already-loaded page. Split out so tests can use set_content."""
    d = page.evaluate(_JS)
    return Recon(url=url, title=d["title"], **{k: d[k] for k in ("elements", "search", "pagination")})


def recon(url: str, timeout: int = RECON_TIMEOUT) -> Recon:
    """Load `url` and reduce it. Raises on an unreachable or refusing site --
    retry_loop.py turns that into a `failed` job the user can read."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            resp = page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            # goto only raises on transport failure; a 403 page loads fine and
            # would otherwise reach the LLM as a "please enable JavaScript" wall.
            if resp is not None and resp.status >= 400:
                blocked = " (blocked -- bot protection or auth wall)" if resp.status in (401, 403, 429) else ""
                raise RuntimeError(f"{url} returned HTTP {resp.status}{blocked}")
            return reduce_page(page, url)
        finally:
            browser.close()
