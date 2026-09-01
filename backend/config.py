"""Environment-derived settings and every hard limit in the system.

The LLM key is NOT a value in here. This module only loads `.env` into the
environment; generate.py reads GEMINI_API_KEY / GOOGLE_API_KEY at call time so
the secret never sits in a module global (rules.md A3). This module imports stdlib
only, so any module may import it without breaking the table in
architecture.md 2.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

ENV_FILES = (Path(__file__).parent / ".env", Path(__file__).parents[1] / ".env")


def load_env_file(*paths: Path) -> None:
    """Read `KEY=value` lines from a .env into the environment.

    # ponytail: eight lines of stdlib instead of python-dotenv. No export
    # keyword, no interpolation, no multi-line values -- add the dependency
    # the day a .env here actually needs them.

    setdefault, not assignment: a variable already exported in the shell wins
    over the file, which is what anyone running `GEMINI_API_KEY=... uvicorn ...`
    expects. Values are never logged.
    """
    for path in paths or ENV_FILES:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


# Before anything below reads os.getenv, and before generate.py resolves the
# key or the model name -- every module imports this one.
load_env_file()

# Local dev default: MySQL, root, no password, database ai_scripts.
DB: dict = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DB", "ai_scripts"),
}

# --- limits. One place, named, so nothing is a magic number at the call site.
MAX_ATTEMPTS = 3                    # rules.md C14 -- not configurable upward
EXEC_TIMEOUT = 120                  # seconds, wall clock, per subprocess run.
                                    # 60 was fine for one listing page; a run that
                                    # opens ~20 detail pages needs the headroom.
                                    # Also stated in prompts.SYSTEM, which cannot
                                    # interpolate -- change both together.
RECON_TIMEOUT = 30                  # seconds, page load
RECON_SETTLE = 5                    # seconds waited for the network to go quiet
                                    # AFTER the DOM is up. Best effort: a page
                                    # with ad frames or polling never goes idle,
                                    # and that is not a reason to fail the job
EXEC_MEMORY_BYTES = 1_500_000_000   # address-space cap for the generated script
MAX_PROMPT_CHARS = 4_000            # user prompt, validated at the boundary
MAX_NAME_CHARS = 120                # job name -- a label, not a description
MAX_SCRIPT_CHARS = 50_000           # a hand-supplied script; generated ones are
                                    # far smaller (MAX_OUTPUT_TOKENS below)
MAX_ERROR_CHARS = 4_000             # error tail fed back to the LLM as repair context
MAX_OUTPUT_TOKENS = 16_000          # cap on one generated script
LLM_TIMEOUT = 300                   # seconds for one generation call, no retry behind it
STALE_RUNNING_MIN = 10              # a `running` job older than this died with its process

# --- guardrails (backend/guardrails.py)
ALLOW_PRIVATE_URLS = os.getenv("ALLOW_PRIVATE_URLS") == "1"
                                    # off by default: a url resolving to loopback or
                                    # the private network is an SSRF, not a scrape.
                                    # On for local fixture sites -- the test suite
                                    # sets it in conftest.py.


# --- browser. A site behind a WAF blocks the datacenter/geo the request comes
# from, not the request itself, so the only bypass is coming from somewhere
# else: set SCRAPE_PROXY=http://user:pass@host:port. Unset = direct, as before.
def _proxy() -> dict | None:
    """Playwright wants credentials as separate keys, not inside the url."""
    u = urlparse(os.getenv("SCRAPE_PROXY") or "")
    if not u.hostname:
        return None
    port = f":{u.port}" if u.port else ""
    return {"server": f"{u.scheme}://{u.hostname}{port}",
            "username": u.username, "password": u.password}


PROXY = _proxy()

# Headless chromium's default user agent says "HeadlessChrome", which is the
# cheapest thing a bot filter can key on. Override with SCRAPE_UA.
USER_AGENT = os.getenv("SCRAPE_UA") or (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
