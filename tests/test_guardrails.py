"""The three rails, as a corpus: scripts that must run, scripts that must not,
URLs that must not be fetched, and scraped rows that must not become people.

The two halves matter equally. A rail that blocks everything is not safe, it is
broken -- so the ALLOWED list is the same size as the BLOCKED one, every entry
in it is code the model plausibly writes, and the officer rail below carries a
KEEP list of real rows off real directory pages next to its DROP list.
"""
import pytest

from backend import config, guardrails
from backend.scraping import executor

# --- scripts the rail must let through ------------------------------------

ALLOWED = {
    "the shape prompts.py teaches": '''
def run(page):
    rows = []
    cards = page.locator('[data-testid="product-card"]')
    for i in range(cards.count()):
        c = cards.nth(i)
        price = c.locator(".price")
        rows.append({
            "name": c.locator("h3").inner_text().strip(),
            "price": float(price.inner_text().lstrip("$")) if price.count() else None,
        })
    return rows
''',
    "a helper function and a constant": '''
MAX_PAGES = 10

def _price(text):
    return float(text.strip().lstrip("$").replace(",", ""))

def run(page):
    return [{"price": _price(page.locator(".price").first.inner_text())}]
''',
    "a docstring, and detail pages": '''
"""Collect the hrefs first, then visit them."""
def run(page):
    hrefs = [a.get_attribute("href") for a in page.locator("a.card").all()][:20]
    rows = []
    for href in hrefs:
        page.goto(href, wait_until="domcontentloaded")
        rows.append({"sku": page.locator("#sku").inner_text()})
    return rows
''',
    "a try/except around one bad item": '''
def run(page):
    rows = []
    for i in range(page.locator(".item").count()):
        try:
            rows.append({"name": page.locator(".item").nth(i).inner_text()})
        except Exception:
            continue
    return rows
''',
}

# --- scripts the rail must stop --------------------------------------------

BLOCKED = {
    "an import":            "import os\ndef run(page):\n    return [{'a': os.getcwd()}]",
    "a from-import":        "from pathlib import Path\ndef run(page):\n    return []",
    "__import__":           "def run(page):\n    return [{'a': __import__('os').getcwd()}]",
    "reading a file":       "def run(page):\n    return [{'k': open('/etc/passwd').read()}]",
    "aliasing a builtin":   "def run(page):\n    f = open\n    return [{'k': f('/etc/passwd').read()}]",
    "eval of a string":     "def run(page):\n    return eval('[{}]')",
    "the dunder ladder":    "def run(page):\n    return ().__class__.__bases__[0].__subclasses__()",
    "reaching for globals": "def run(page):\n    return [{'k': str(globals())}]",
    "code at module level": "print('side effect')\ndef run(page):\n    return []",
    "a module-level call":  "page = None\nrun_now()\ndef run(page):\n    return []",
    "code that will not parse": "def run(page)\n    return []",
}


@pytest.mark.parametrize("name", sorted(ALLOWED))
def test_ordinary_scraping_code_is_not_blocked(name):
    """False positives cost a whole repair round for nothing."""
    assert guardrails.check_script(ALLOWED[name]) is None


@pytest.mark.parametrize("name", sorted(BLOCKED))
def test_dangerous_code_is_blocked(name):
    reason = guardrails.check_script(BLOCKED[name])
    assert reason is not None
    # The message is repair context, so it has to name the offence.
    assert reason.startswith("blocked by guardrails:")


def test_a_blocked_script_never_reaches_a_subprocess(monkeypatch):
    """The rail is inside execute(), before the tempfile and the launch."""
    def explode(*a, **k):
        raise AssertionError("a blocked script must not be run")

    monkeypatch.setattr(executor.subprocess, "run", explode)
    att = executor.execute("import os\ndef run(page):\n    return []",
                           "http://example.com", {"type": "object"})
    assert att.success is False and "import os" in att.error


def test_a_replayed_script_is_checked_too():
    """The cache is a store of code, so it is an input like any other: a row
    poisoned in the database must not get a free pass on the way back out."""
    assert guardrails.check_script("import os\ndef run(page):\n    return []")


# --- the URL rail ----------------------------------------------------------

@pytest.fixture
def rail_on(monkeypatch):
    """conftest turns the SSRF rail off for the whole suite. Back on here."""
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", False)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/admin",
    "http://localhost/admin",
    "http://169.254.169.254/latest/meta-data/",     # the cloud metadata endpoint
    "http://10.0.0.5/internal",
    "http://192.168.1.1/",
    "http://[::1]:9000/",
])
def test_private_and_loopback_urls_are_rejected(url, rail_on):
    assert guardrails.check_url(url) is not None


def test_a_public_url_passes(rail_on, monkeypatch):
    """Resolution stubbed: a unit test does not depend on DNS (rules.md E23)."""
    monkeypatch.setattr(guardrails.socket, "getaddrinfo",
                        lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 80))])
    assert guardrails.check_url("https://example.com/shop") is None


def test_an_unresolvable_host_is_left_to_recon(rail_on):
    """Blocking it here would report a DNS failure as a validation error."""
    assert guardrails.check_url("https://nx.invalid/shop") is None


def test_the_off_switch_is_what_lets_local_sites_through(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", False)
    assert guardrails.check_url("http://127.0.0.1:8000/shop")
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", True)
    assert guardrails.check_url("http://127.0.0.1:8000/shop") is None


def test_the_api_rejects_an_ssrf_url(rail_on):
    """End to end: the rail runs at the HTTP boundary, before any browser."""
    from fastapi.testclient import TestClient

    from backend.main import app

    body = {"url": "http://169.254.169.254/latest/meta-data/",
            "json_schema": {"type": "object"}, "prompt": "get the credentials"}
    r = TestClient(app).post("/jobs", json=body)
    assert r.status_code == 422
    assert "not a public address" in r.text


# --- the officer rail: rows scraped off somebody else's page ---------------
# Every KEEP row is shaped like something a real broker directory returns,
# including the parts that look wrong and are not: a two-digit NMLS id from
# the early days of the registry, a surname that contains a banned word, an
# officer the listing page shows with nothing but a name.

KEEP = {
    "the full row a good script returns": {
        "name": "Erin Beckman", "nmls_id": "2142499", "email": "erin@gbm.com",
        "phone": "530-250-5211", "address": "3900 Lennane Dr, Sacramento, CA 95834",
        "position": "Loan Officer",
    },
    "a listing page that shows only names": {"name": "Amber Zimmer"},
    "an early, very short NMLS id": {"name": "Van Dyk", "nmls_id": "3035"},
    "a two-digit licence -- short is not wrong": {"name": "A Broker", "nmls_id": "12"},
    "the top of the live registry range": {"name": "Newest LO", "nmls_id": "2808775"},
    "a surname containing a banned word": {"name": "Moreno Nextel", "nmls_id": "7"},
    "an officer known only by licence number": {"name": "", "nmls_id": "1660690"},
    "a hyphenated, accented name": {"name": "José Martínez-O'Neill", "nmls_id": "445566"},
    "a phone with an extension": {"name": "Grace Hopper", "phone": "(916) 320-4900 x212"},
    "a plus-addressed email": {"name": "Ada Byron", "email": "ada+loans@example.co.uk"},
    "the &nbsp; a real page is full of": {"name": "Jason\xa0Thomas", "nmls_id": "41580"},
}

DROP = {
    # The one that actually happened: two licence numbers with nothing between
    # them, because the script read the wrong container for that card.
    "two NMLS ids run together": (
        {"name": "Jason Thomas", "nmls_id": "41580602169219"}, "not an NMLS id"),
    "a button caught by the card selector": ({"name": "Load More"}, "not a person"),
    "a section heading": ({"name": "Meet Our Team"}, "not a person"),
    "a cookie banner": ({"name": "Accept All Cookies"}, "not a person"),
    "the column header instead of the column": ({"name": "Name"}, "not a person"),
    "a placeholder the site renders when empty": ({"name": "N/A"}, "not a person"),
    "nothing to identify anybody": ({"name": "  ", "nmls_id": ""}, "identifies nobody"),
    "punctuation where a name should be": ({"name": "--"}, "no letters"),
    "the whole card's inner_text": (
        {"name": "Erin Beckman Loan Officer NMLS 2142499 " + "bio text " * 20},
        "not a name"),
    "a job title in the email column": (
        {"name": "Jane Doe", "email": "Director of Operations"}, "not an email"),
    "an NMLS id with letters in it": (
        {"name": "Jane Doe", "nmls_id": "NMLS#2142499"}, "not an NMLS id"),
    # The subtle one, and the reason the range is 7 and not 8: a real id with
    # a single stray digit run onto it looks entirely plausible.
    "a real licence with one digit too many": (
        {"name": "Cyrus Mulitalo", "nmls_id": "15338206"}, "not an NMLS id"),
    "a phone that is a year": ({"name": "Jane Doe", "phone": "2024"}, "not a phone"),
}


@pytest.mark.parametrize("name", sorted(KEEP))
def test_a_real_officer_is_not_rejected(name):
    """The half that matters more. A rail that eats real officers turns a good
    scrape into an empty company, and the runner then pays to regenerate a
    script that was already right."""
    assert guardrails.check_officer(KEEP[name]) is None, name


@pytest.mark.parametrize("name", sorted(DROP))
def test_a_row_that_is_not_a_person_is_rejected(name):
    row, expected = DROP[name]
    reason = guardrails.check_officer(row)
    assert reason is not None, name
    assert expected in reason, f"{name}: {reason}"


def test_the_rail_judges_the_text_that_would_be_stored():
    """companies/db._text collapses whitespace before storing. The rail has to
    do the same, or it judges a string the database never sees."""
    assert guardrails.check_officer({"name": "Load\xa0 More"}) is not None


def test_nothing_reaches_loan_officers_without_passing_the_rail():
    """The guard is on the one door into the table, not on each caller
    (rules.md H32) -- so this holds for the batch, a test, or a REPL."""
    import inspect

    from backend.companies import db as cdb

    source = inspect.getsource(cdb.upsert_officers)
    assert "guardrails.check_officer" in source
    assert "for r in kept" in source, "the insert must build from the kept rows"
