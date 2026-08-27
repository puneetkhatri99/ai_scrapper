"""Never calls the live API (rules.md E22) -- the HTTP client is stubbed."""
import ast

import pytest

from backend.generate import (
    MODEL,
    SYSTEM_MESSAGE,
    _extract_code,
    build_user_block,
    generate,
)
from backend.models import Attempt
from backend.recon import Recon

GOOD = '''Here you go.

```python
def run(page) -> list[dict]:
    return [{"name": page.title()}]
```
'''


class FakeResponse:
    """Just enough of httpx.Response for generate() to read."""

    is_error = False
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class FakeClient:
    """Records every post(**kwargs) and replays a canned chat completion."""

    def __init__(self, *texts: str, refusal: str | None = None,
                 finish_reason: str = "stop"):
        self._texts = list(texts)
        self._refusal = refusal
        self._finish = finish_reason
        self.calls: list[dict] = []
        # Second call onward reads the cached prefix, as the real API would.
        self.cached = [0, 1467]

    def post(self, url, *, json, headers):
        self.calls.append({"url": url, **json, "headers": headers})
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        message = {"role": "assistant", "content": text}
        if self._refusal:
            message["refusal"] = self._refusal
        return FakeResponse({
            "choices": [{"message": message, "finish_reason": self._finish}],
            "usage": {
                "prompt_tokens": 1500,
                "completion_tokens": 400,
                "prompt_tokens_details": {
                    "cached_tokens": self.cached[min(len(self.calls) - 1,
                                                     len(self.cached) - 1)],
                },
            },
        })


RECON = Recon(
    url="https://fixture.test/shop",
    title="Shop",
    elements=[{"tag": "a", "id": None, "class": "card", "testid": "product-1",
               "aria": None, "text": "Running Shoe", "href": "/p/1"}],
    search={"selector": 'input[name="q"]', "submit": "#search-go"},
    pagination={"kind": "next_link", "selector": '[aria-label="Next page"]'},
)
SCHEMA = {"type": "array", "items": {"type": "object",
                                     "properties": {"name": {"type": "string"}}}}


def _gen(client, prompt="get the shoes", prior=None):
    return generate(RECON, SCHEMA, prompt, prior, client=client)


def test_returns_a_parsable_run_function():
    code = _gen(FakeClient(GOOD))
    fn = ast.parse(code).body[0]
    assert isinstance(fn, ast.FunctionDef) and fn.name == "run"
    assert len(fn.args.args) == 1


def test_prose_with_no_fence_raises():
    with pytest.raises(ValueError, match="no ```python fence"):
        _gen(FakeClient("I cannot help with that, but here is some advice."))


def test_syntax_error_raises():
    with pytest.raises(ValueError, match="does not parse"):
        _gen(FakeClient("```python\ndef run(page:\n    return []\n```"))


def test_wrong_function_name_raises():
    with pytest.raises(ValueError, match="no top-level `def run`"):
        _gen(FakeClient("```python\ndef scrape(page):\n    return []\n```"))


def test_wrong_arity_raises():
    with pytest.raises(ValueError, match="expected 1"):
        _gen(FakeClient("```python\ndef run(page, url):\n    return []\n```"))


def test_refusal_raises_and_names_itself():
    with pytest.raises(ValueError, match="refused"):
        _gen(FakeClient(GOOD, refusal="cyber"))


def test_truncated_output_raises_instead_of_reaching_the_executor():
    """A script cut off at the token cap parses as prose, not as run()."""
    with pytest.raises(ValueError, match="token cap"):
        _gen(FakeClient(GOOD, finish_reason="length"))


def test_missing_credentials_say_which_variable_to_set(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="XAI_API_KEY"):
        generate(RECON, SCHEMA, "get the shoes")        # no client: real path


def test_system_prefix_is_byte_identical_across_calls():
    """The invariant behind cache_read_input_tokens > 0 (rules.md C12)."""
    c = FakeClient(GOOD)
    _gen(c, prompt="get the shoes")
    generate(Recon("https://other.test", "Other", [], None, None),
             {"type": "object"}, "something else",
             Attempt(code="def run(page): pass", output=None, error="boom", success=False),
             client=c)
    assert c.calls[0]["messages"][0] == c.calls[1]["messages"][0] == SYSTEM_MESSAGE
    assert c.calls[0]["messages"][1] != c.calls[1]["messages"][1]   # volatile half varied


def test_request_shape_matches_the_provider():
    c = FakeClient(GOOD)
    _gen(c)
    kw = c.calls[0]
    assert kw["url"] == "https://api.x.ai/v1/chat/completions"
    assert kw["model"] == MODEL and MODEL.startswith("grok")
    assert kw["messages"][0]["role"] == "system"      # frozen prefix goes first
    assert kw["headers"]["authorization"].startswith("Bearer ")
    assert "sk-" not in str(c.calls[0]["messages"])   # no key in the payload


def test_user_block_carries_the_prior_error_on_repair():
    prior = Attempt(code="def run(page): return []", output=None,
                    error="TimeoutError: waiting for selector", success=False)
    block = build_user_block(RECON, SCHEMA, "get the shoes", prior)
    assert "TimeoutError: waiting for selector" in block
    assert "previous attempt failed" in block
    assert "previous attempt" not in build_user_block(RECON, SCHEMA, "get the shoes")


def test_recon_renders_compact_and_keeps_stable_attributes():
    block = build_user_block(RECON, SCHEMA, "get the shoes")
    assert '[data-testid="product-1"]' in block
    assert "Running Shoe" in block
    assert "next_link" in block
    assert "<" not in block.split("# JSON Schema")[0]   # no raw HTML (rules.md C13)


def test_extract_code_takes_the_first_fence_only():
    code = _extract_code("```python\ndef run(page):\n    return []\n```\n"
                         "```python\ndef run(page):\n    return [1]\n```")
    assert "return []" in code and "return [1]" not in code
