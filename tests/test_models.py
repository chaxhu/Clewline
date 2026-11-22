"""Tests for core/models.py. No network calls: fake keys, fake models, and no real .invoke()."""

from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelInvalidRequestError,
    ModelRateLimitError,
    ModelTimeoutError,
    OutputParserException,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mistralai import ChatMistralAI
from langchain_openai import ChatOpenAI

from core import models
from core.models import ModelConfigError, Provider, get_chat_model

FAKE_GEMINI = "fake-gemini-key-123"
FAKE_OPENAI = "fake-openai-key-456"
FAKE_MISTRAL = "fake-mistral-key-789"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test from a known environment, ignoring the real .env values.
    Fallback is off here; the fallback tests below switch it on."""
    for name in ("MODEL_PROVIDER", "GEMINI_MODEL", "OPENAI_MODEL", "MISTRAL_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", FAKE_GEMINI)
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI)
    monkeypatch.setenv("MISTRAL_API_KEY", FAKE_MISTRAL)
    monkeypatch.setenv("MODEL_FALLBACK", "off")
    monkeypatch.setattr(models, "tracing_configured", lambda: False)


# ---- Choosing a provider and model ------------------------------------------

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
    assert get_chat_model("mistral").model == models.PROVIDERS["mistral"].default_model


def test_mistral_provider(monkeypatch):
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-from-env")
    llm = get_chat_model("mistral")
    assert isinstance(llm, ChatMistralAI)
    assert llm.model == "mistral-from-env"
    assert FAKE_MISTRAL not in repr(llm)


def test_unknown_provider():
    with pytest.raises(ModelConfigError, match="Choose one of: gemini, mistral, openai"):
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
    for key in (FAKE_GEMINI, FAKE_OPENAI, FAKE_MISTRAL):
        assert key not in str(excinfo.value)


def test_key_is_not_shown_in_repr():
    llm = get_chat_model()
    assert FAKE_GEMINI not in repr(llm)


def test_every_model_carries_provider_and_model_metadata():
    llm = get_chat_model("gemini")
    # LangChain adds its own "lc_versions" entry too; we only check ours.
    assert llm.metadata.items() >= {"provider": "gemini", "model": "gemini-3.8-flash"}.items()


def test_langfuse_handler_attached_when_tracing_configured(monkeypatch):
    monkeypatch.setattr(models, "tracing_configured", lambda: True)
    llm = get_chat_model()
    assert llm.callbacks and type(llm.callbacks[0]).__name__ == "LangchainCallbackHandler"


def test_no_handler_when_tracing_not_configured():
    assert not get_chat_model().callbacks


# ---- Fallback switch --------------------------------------------------------

def test_fallback_on_by_default(monkeypatch):
    monkeypatch.delenv("MODEL_FALLBACK")
    llm = get_chat_model()
    assert [type(m) for m in (llm.runnable, *llm.fallbacks)] == [ChatGoogleGenerativeAI, ChatMistralAI]
    assert llm.fallbacks[0].metadata["fallback_for"] == "gemini"


@pytest.mark.parametrize("value", ["off", "OFF", "false", "0", "no"])
def test_fallback_off_from_env(monkeypatch, value):
    monkeypatch.setenv("MODEL_FALLBACK", value)
    assert isinstance(get_chat_model(), ChatGoogleGenerativeAI)


def test_argument_beats_env_for_fallback(monkeypatch):
    monkeypatch.setenv("MODEL_FALLBACK", "on")
    assert isinstance(get_chat_model(fallback=False), ChatGoogleGenerativeAI)
    monkeypatch.setenv("MODEL_FALLBACK", "off")
    assert isinstance(get_chat_model(fallback=True).fallbacks[0], ChatMistralAI)


def test_missing_mistral_key_turns_fallback_off_with_a_warning(monkeypatch):
    monkeypatch.setenv("MODEL_FALLBACK", "on")
    monkeypatch.delenv("MISTRAL_API_KEY")
    with pytest.warns(UserWarning, match="fallback is off: MISTRAL_API_KEY is not set"):
        llm = get_chat_model()
    assert isinstance(llm, ChatGoogleGenerativeAI)


def test_forced_fallback_without_key_is_an_error(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY")
    with pytest.raises(ModelConfigError, match="MISTRAL_API_KEY"):
        get_chat_model(fallback=True)


def test_providers_without_a_fallback(monkeypatch):
    monkeypatch.setenv("MODEL_FALLBACK", "on")
    assert isinstance(get_chat_model("openai"), ChatOpenAI)
    with pytest.raises(ModelConfigError, match="no fallback provider for 'openai'"):
        get_chat_model("openai", fallback=True)


def test_tracing_handler_goes_on_the_whole_chain(monkeypatch):
    monkeypatch.setattr(models, "tracing_configured", lambda: True)
    llm = get_chat_model(fallback=True)
    handlers = llm.config["callbacks"]
    assert type(handlers[0]).__name__ == "LangchainCallbackHandler"
    # The primary model keeps only the recorder, so the call is not traced twice.
    assert [type(h) for h in llm.bound.runnable.callbacks] == [models.FallbackRecorder]


# ---- Fallback behaviour, with fake models -------------------------------------

class FakeChat(BaseChatModel):
    """A chat model that returns a fixed reply, or raises a given error."""

    reply: str = "ok"
    fail_with: Any = None
    calls: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])

    @property
    def _llm_type(self) -> str:
        return "fake"


class FakeLangfuse:
    def __init__(self):
        self.events = []

    def create_event(self, **kwargs):
        self.events.append(kwargs)


@pytest.fixture
def fakes(monkeypatch):
    """Swap the real Gemini and Mistral builders for fake models, and capture
    what would be sent to Langfuse. Returns a dict to inspect after a call."""
    state = {"gemini_error": None, "gemini_reply": "from gemini", "built": {}, "trace_metadata": []}
    langfuse = FakeLangfuse()
    state["langfuse"] = langfuse

    def builder(provider_name):
        def build(model, api_key, temperature, timeout, max_retries, metadata):
            fail = state["gemini_error"] if provider_name == "gemini" else None
            reply = state["gemini_reply"] if provider_name == "gemini" else "from mistral"
            fake = FakeChat(reply=reply, fail_with=fail, metadata=metadata)
            state["built"][provider_name] = fake
            return fake
        return build

    for name in ("gemini", "mistral"):
        real = models.PROVIDERS[name]
        monkeypatch.setitem(models.PROVIDERS, name, Provider(real.key_env, real.model_env, real.default_model, builder(name)))

    @contextmanager
    def fake_propagate(metadata):
        state["trace_metadata"].append(metadata)
        yield

    class NoOpHandler(BaseCallbackHandler):
        pass

    monkeypatch.setattr(models, "tracing_configured", lambda: True)
    monkeypatch.setattr(models, "get_langchain_handler", NoOpHandler)
    monkeypatch.setattr(models, "get_langfuse", lambda: langfuse)
    monkeypatch.setattr(models, "propagate_attributes", fake_propagate)
    return state


@pytest.mark.parametrize(
    "error, reason",
    [
        (ModelRateLimitError("429 quota exceeded"), "rate_limit"),
        (ModelAPIError("503 service unavailable"), "server_error"),
        (ModelTimeoutError("request timed out"), "timeout"),
        (httpx.ReadTimeout("read timed out"), "timeout"),
        (ModelConnectionError("could not connect"), "connection_error"),
        (httpx.ConnectError("connection refused"), "connection_error"),
    ],
)
def test_call_failure_falls_back_to_mistral_and_is_recorded(fakes, error, reason):
    fakes["gemini_error"] = error
    reply = get_chat_model(fallback=True).invoke("hello")

    assert reply.text == "from mistral"
    assert fakes["built"]["gemini"].calls == 1
    assert fakes["built"]["mistral"].calls == 1

    expected = {
        "fallback_from": "gemini/gemini-3.8-flash",
        "fallback_to": "mistral/mistral-small-2603",
        "fallback_reason": reason,
        "fallback_error": f"{type(error).__name__}: {error}",
    }
    [event] = fakes["langfuse"].events
    assert event["name"] == "model_fallback"
    assert event["level"] == "WARNING"
    assert event["metadata"] == expected
    assert "mistral/mistral-small-2603 answered instead" in event["status_message"]
    assert fakes["trace_metadata"] == [expected]


def test_answering_model_is_labelled_as_mistral(fakes):
    fakes["gemini_error"] = ModelRateLimitError("429")
    get_chat_model(fallback=True).invoke("hello")
    gemini, mistral = fakes["built"]["gemini"].metadata, fakes["built"]["mistral"].metadata
    assert gemini["provider"] == "gemini" and gemini["model"] == "gemini-3.8-flash"
    assert "fallback_for" not in gemini
    assert mistral["provider"] == "mistral" and mistral["model"] == "mistral-small-2603"
    assert mistral["fallback_for"] == "gemini"


def test_no_fallback_when_gemini_answers(fakes):
    reply = get_chat_model(fallback=True).invoke("hello")
    assert reply.text == "from gemini"
    assert fakes["built"]["mistral"].calls == 0
    assert fakes["langfuse"].events == []
    assert fakes["trace_metadata"] == []


@pytest.mark.parametrize(
    "error",
    [
        ModelInvalidRequestError("400 bad request"),
        ModelAuthenticationError("401 wrong key"),
        ValueError("a bug in our code"),
    ],
)
def test_other_errors_do_not_fall_back(fakes, error):
    fakes["gemini_error"] = error
    with pytest.raises(type(error)):
        get_chat_model(fallback=True).invoke("hello")
    assert fakes["built"]["mistral"].calls == 0
    assert fakes["langfuse"].events == []


def test_bad_output_does_not_fall_back(fakes):
    fakes["gemini_reply"] = "this is not JSON"
    chain = get_chat_model(fallback=True) | JsonOutputParser()
    with pytest.raises(OutputParserException):
        chain.invoke("give me JSON")
    assert fakes["built"]["mistral"].calls == 0
    assert fakes["langfuse"].events == []


def test_with_fallback_off_a_call_failure_is_raised(fakes):
    """Evaluation runs: the failure surfaces as an error, so it can be counted as one."""
    fakes["gemini_error"] = ModelRateLimitError("429")
    with pytest.raises(models.CALL_FAILURES):
        get_chat_model(fallback=False).invoke("hello")
    assert "mistral" not in fakes["built"]
    assert fakes["langfuse"].events == []


def test_long_error_messages_are_cut_to_fit_langfuse(fakes):
    fakes["gemini_error"] = ModelAPIError("x" * 500)
    get_chat_model(fallback=True).invoke("hello")
    assert len(fakes["langfuse"].events[0]["metadata"]["fallback_error"]) == 150
