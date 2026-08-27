"""The .env loader: it is the only reason the API key reaches generate.py."""
import os

from backend.config import load_env_file


def test_loads_keys_and_ignores_comments_and_blanks(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nXAI_API_KEY="from-file"\nGROK_MODEL = grok-4.3\n'
                   "not a pair\n")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_MODEL", raising=False)

    load_env_file(env)

    assert os.environ["XAI_API_KEY"] == "from-file"      # quotes stripped
    assert os.environ["GROK_MODEL"] == "grok-4.3"        # spaces stripped


def test_a_real_environment_variable_wins(tmp_path, monkeypatch):
    """Otherwise `XAI_API_KEY=other uvicorn ...` would silently do nothing."""
    env = tmp_path / ".env"
    env.write_text("XAI_API_KEY=from-file\n")
    monkeypatch.setenv("XAI_API_KEY", "from-shell")

    load_env_file(env)

    assert os.environ["XAI_API_KEY"] == "from-shell"


def test_a_missing_file_is_not_an_error(tmp_path):
    load_env_file(tmp_path / "nope.env")        # raises nothing
