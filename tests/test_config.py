"""The .env loader: it is the only reason the API key reaches generate.py."""
import os

from backend.config import load_env_file


def test_loads_keys_and_ignores_comments_and_blanks(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nGEMINI_API_KEY="from-file"\nGEMINI_MODEL = gemini-2.5-flash\n'
                   "not a pair\n")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    load_env_file(env)

    assert os.environ["GEMINI_API_KEY"] == "from-file"      # quotes stripped
    assert os.environ["GEMINI_MODEL"] == "gemini-2.5-flash"        # spaces stripped


def test_a_real_environment_variable_wins(tmp_path, monkeypatch):
    """Otherwise `GEMINI_API_KEY=other uvicorn ...` would silently do nothing."""
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=from-file\n")
    monkeypatch.setenv("GEMINI_API_KEY", "from-shell")

    load_env_file(env)

    assert os.environ["GEMINI_API_KEY"] == "from-shell"


def test_a_missing_file_is_not_an_error(tmp_path):
    load_env_file(tmp_path / "nope.env")        # raises nothing
