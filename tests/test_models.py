"""Tests for core/models.py. No network calls: fake keys, and no .invoke()."""

import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from core import models
from core.models import ModelConfigError, get_chat_model

FAKE_GEMINI = "fake-gemini-key-123"
FAKE_OPENAI = "fake-openai-key-456"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test from a known environment, ignoring the real .env values."""
    for name in ("MODEL_PROVIDER", "GEMINI_MODEL", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", FAKE_GEMINI)
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI)
    monkeypatch.setattr(models, "tracing_configured", lambda: False)


def test_default_provider_is_gemini():
    llm = get_chat_model()
    assert isinstance(llm, ChatGoogleGenerativeAI)
    assert llm.temperature == 0.0


def test_provider_from_env(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    assert isinstance(get_chat_model(), ChatOpenAI)


def test_argument_beats_env(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    assert isinstance(get_chat_model("gemini"), ChatGoogleGenerativeAI)


def test_provider_name_is_case_insensitive():
    assert isinstance(get_chat_model(" OpenAI "), ChatOpenAI)


def test_model_name_from_env_and_argument(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-from-env")
    assert get_chat_model().model.endswith("gemini-from-env")
    assert get_chat_model(model="gemini-from-arg").model.endswith("gemini-from-arg")


def test_builtin_default_model_names():
    assert get_chat_model("gemini").model.endswith(models.PROVIDERS["gemini"].default_model)
    assert get_chat_model("openai").model_name == models.PROVIDERS["openai"].default_model


def test_unknown_provider():
    with pytest.raises(ModelConfigError, match="Choose one of: gemini, openai"):
        get_chat_model("claude")


@pytest.mark.parametrize("value", ["", "your-gemini-key-here"])
def test_missing_or_placeholder_key(monkeypatch, value):
    monkeypatch.setenv("GOOGLE_API_KEY", value)
    with pytest.raises(ModelConfigError, match="GOOGLE_API_KEY is not set"):
        get_chat_model("gemini")


def test_error_messages_never_contain_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(ModelConfigError) as excinfo:
        get_chat_model("openai")
    assert FAKE_GEMINI not in str(excinfo.value)
    assert FAKE_OPENAI not in str(excinfo.value)


def test_key_is_not_shown_in_repr():
    llm = get_chat_model()
    assert FAKE_GEMINI not in repr(llm)


def test_langfuse_handler_attached_when_tracing_configured(monkeypatch):
    monkeypatch.setattr(models, "tracing_configured", lambda: True)
    llm = get_chat_model()
    assert llm.callbacks and type(llm.callbacks[0]).__name__ == "LangchainCallbackHandler"


def test_no_handler_when_tracing_not_configured():
    assert not get_chat_model().callbacks
