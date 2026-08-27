import json
from dataclasses import asdict
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from backend.recon import reduce_page

FIXTURE = (Path(__file__).parent / "fixtures" / "shop.html").read_text()


@pytest.fixture(scope="module")
def browser():
    # One playwright per process -- sync_playwright can't nest.
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _recon(browser, html: str, url: str = "https://fixture.test/shop"):
    # No network (rules.md E23) -- pages are served via set_content.
    page = browser.new_page()
    page.set_content(html)
    r = reduce_page(page, url)
    page.close()
    return r


@pytest.fixture(scope="module")
def shop(browser):
    return _recon(browser, FIXTURE)


def test_search_uses_the_submit_button(shop):
    assert shop.search["selector"] == 'input[name="q"]'
    assert shop.search["submit"] == "#search-go"


def test_pagination_is_a_next_link(shop):
    assert shop.pagination == {"kind": "next_link", "selector": '[aria-label="Next page"]'}


def test_every_product_card_survives_the_reduction(shop):
    testids = {e["testid"] for e in shop.elements}
    assert {f"product-{n}" for n in range(1, 11)} <= testids


def test_scripts_and_styles_are_gone(shop):
    blob = json.dumps(shop.elements)
    assert "<script>" not in blob and "__junk" not in blob
    assert not any(e["tag"] in ("script", "style") for e in shop.elements)


def test_output_is_compact(shop):
    assert len(json.dumps(asdict(shop))) < 40_000


def test_bare_page_reports_nothing_found(browser):
    r = _recon(browser, "<body><p>just words</p></body>", "https://fixture.test/bare")
    assert r.search is None and r.pagination is None
    assert [e["text"] for e in r.elements] == ["just words"]


def test_numbered_pagination(browser):
    r = _recon(browser, '<body><div id="pager"><a href="?p=1">1</a>'
                        '<a href="?p=2">2</a><a href="?p=3">3</a></div></body>')
    assert r.pagination == {"kind": "numbered", "selector": "#pager"}
