"""Tests for core/tracing.py and scripts/generate_secrets.py. No network calls."""

import re

import pytest

from core import tracing


def test_observe_keeps_return_value_and_nesting():
    @tracing.observe()
    def inner(x):
        return x * 2

    @tracing.observe()
    def outer(x):
        return inner(x) + 1

    assert outer(3) == 7


@pytest.mark.parametrize("missing", tracing.REQUIRED_VARS)
def test_tracing_configured_needs_every_var(monkeypatch, missing):
    for name in tracing.REQUIRED_VARS:
        monkeypatch.setenv(name, "x")
    assert tracing.tracing_configured()
    monkeypatch.delenv(missing)
    assert not tracing.tracing_configured()


def test_check_connection_false_without_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert tracing.check_connection() is False


# ---------- generate_secrets ----------

@pytest.fixture
def secrets_script(tmp_path, monkeypatch):
    """Point the script at a temporary folder so the real .env is never touched."""
    from scripts import generate_secrets as gs

    example = tmp_path / ".env.example"
    example.write_text("GOOGLE_API_KEY=keep-me\nPOSTGRES_PASSWORD=change-me\nENCRYPTION_KEY=change-me\n")
    monkeypatch.setattr(gs, "ENV", tmp_path / ".env")
    monkeypatch.setattr(gs, "EXAMPLE", example)
    return gs


def read_env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def test_generate_secrets_fills_placeholders(secrets_script, capsys):
    secrets_script.main()
    env = read_env(secrets_script.ENV)

    assert env["GOOGLE_API_KEY"] == "keep-me"
    assert re.fullmatch(r"[0-9a-f]{64}", env["ENCRYPTION_KEY"])
    for name in secrets_script.SECRETS:  # every secret present and random-looking
        assert env[name] != "change-me" and len(env[name]) >= 48

    printed = capsys.readouterr().out
    assert env["POSTGRES_PASSWORD"] not in printed  # values are never printed


def test_generate_secrets_is_safe_to_run_twice(secrets_script):
    secrets_script.main()
    first = read_env(secrets_script.ENV)
    secrets_script.main()
    assert read_env(secrets_script.ENV) == first
