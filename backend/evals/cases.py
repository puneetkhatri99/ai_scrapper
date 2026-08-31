"""What "the results are fine" means, case by case.

Each case is a local page, a prompt, a schema, and the exact rows a correct
scraper returns from it. Local because an eval whose expected output changes
when someone else edits their website measures their deploys, not our pipeline
(rules.md E23 applies here for the same reason it applies to tests).

Add a case by adding a page under sites/ and a Case here -- nothing else.
"""
from dataclasses import dataclass, field
from typing import Callable

from backend import guardrails
from backend.companies.runner import OFFICER_PROMPT, OFFICER_SCHEMA


@dataclass(frozen=True)
class Case:
    name: str
    page: str
    prompt: str
    schema: dict
    expect: list[dict]
    tests: str = ""                   # the capability this case is here to measure
    keys: tuple = field(default=())   # compared keys; defaults to expect's
    # The data rail this case's rows would face in production, if any. Declared
    # per case rather than hardcoded in run.py, so the runner stays generic and
    # a case brings its own definition of "and is this row true?".
    rail: Callable[[dict], str | None] | None = None

    def compared(self) -> tuple:
        return self.keys or tuple(self.expect[0])


_PRODUCT = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "price": {"type": "number"}},
    "required": ["name"],
}

CASES = [
    Case(
        name="flat-list",
        page="list.html",
        prompt="Get every product on the page with its name and price.",
        schema=_PRODUCT,
        tests="the baseline: right container, currency coerced, missing field is None",
        expect=[
            {"name": "Aurora Runner", "price": 129.0},
            {"name": "Basalt Trainer", "price": 89.5},
            {"name": "Cinder Trail", "price": 1299.0},      # comma in the source
            {"name": "Dune Walker", "price": 45.0},
            {"name": "Ember Court", "price": None},         # no price element
            {"name": "Frost Glide", "price": 210.75},
        ],
    ),
    Case(
        name="pagination",
        page="page1.html",
        prompt="Get every jacket across all pages, with name and price.",
        schema=_PRODUCT,
        tests="follows 'Next page' once and stops at the end instead of looping",
        expect=[
            {"name": "Alpha Jacket", "price": 20.0},
            {"name": "Bravo Jacket", "price": 30.0},
            {"name": "Charlie Jacket", "price": 40.0},
            {"name": "Delta Jacket", "price": 50.0},
            {"name": "Echo Jacket", "price": 60.0},
            {"name": "Foxtrot Jacket", "price": 70.0},
            {"name": "Golf Jacket", "price": 80.0},
            {"name": "Hotel Jacket", "price": 90.0},
        ],
    ),
    Case(
        name="first-four",
        page="page1.html",
        prompt="Get the first 4 jackets only. Do not go to the next page.",
        schema=_PRODUCT,
        tests="stops at the count asked for -- over-fetching is a failure too",
        expect=[
            {"name": "Alpha Jacket", "price": 20.0},
            {"name": "Bravo Jacket", "price": 30.0},
            {"name": "Charlie Jacket", "price": 40.0},
            {"name": "Delta Jacket", "price": 50.0},
        ],
    ),
    # The one case that measures production. Everything above uses a prompt
    # written for the eval; this one imports the frozen prompt and schema the
    # broker batch actually sends, so a change to either shows up here as a
    # score before it shows up as 67 bad scrapes.
    Case(
        name="loan-officers",
        page="officers/team.html",
        prompt=OFFICER_PROMPT,
        schema=OFFICER_SCHEMA,
        tests=("the production officer prompt: opens each profile for the "
               "details, leaves a missing licence blank, skips the 'Load More' "
               "card, and does not invent a position"),
        # Compared on identity and the two fields a script most often gets
        # wrong -- the licence it concatenates and the title it invents.
        keys=("name", "nmls_id", "position"),
        rail=guardrails.check_officer,
        expect=[
            {"name": "Dana Okonkwo", "nmls_id": "1874325", "position": "Senior Loan Officer"},
            {"name": "Marcus Reyes", "nmls_id": "992014", "position": "Branch Manager"},
            {"name": "Priya Raman", "nmls_id": "2310588", "position": "Loan Officer"},
            # No licence on the page. "" and not a guess: the schema makes
            # every field but `name` optional precisely so a model does not
            # have to fill this in.
            {"name": "Tomás Iglesias", "nmls_id": "", "position": "Loan Officer"},
        ],
    ),
    Case(
        name="detail-pages",
        page="catalog.html",
        prompt=("For each product in the catalog get its name and its SKU. "
                "The SKU is only on the product's own page."),
        schema={
            "type": "object",
            "properties": {"name": {"type": "string"}, "sku": {"type": "string"}},
            "required": ["name", "sku"],
        },
        tests="collects hrefs before navigating, then visits each detail page",
        expect=[
            {"name": "Lantern Desk", "sku": "LD-1001"},
            {"name": "Marble Shelf", "sku": "MS-1002"},
            {"name": "Nickel Lamp", "sku": "NL-1003"},
            {"name": "Oak Stool", "sku": "OS-1004"},
        ],
    ),
]
