"""Tests for core/models.py. No network calls: fake keys, fake models, a fake clock."""

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelInvalidRequestError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
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
from core.models import ModelConfigError, Provider, RetriesExhausted, SpendCapReached, get_chat_model

FAKE_GEMINI = "fake-gemini-key-123"
FAKE_OPENAI = "fake-openai-key-456"
FAKE_MISTRAL = "fake-mistral-key-789"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test from a known environment, ignoring the real .env values.
    Fallback is off here; the fallback tests below switch it on."""
    for name in ("MODEL_PROVIDER", "GEMINI_MODEL", "OPENAI_MODEL", "MISTRAL_MODEL",
                 "MODEL_MAX_ATTEMPTS", "MAX_RUN_COST_USD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", FAKE_GEMINI)
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI)
    monkeypatch.setenv("MISTRAL_API_KEY", FAKE_MISTRAL)
    monkeypatch.setenv("MODEL_FALLBACK", "off")
    monkeypatch.setattr(models, "tracing_configured", lambda: False)
    models.start_run()  # a fresh budget for every test


@pytest.fixture(autouse=True)
def fake_clock(monkeypatch):
    """Record every wait instead of sleeping. Jitter is fixed at its top value (x1.0)."""
    sleeps: list[float] = []
    monkeypatch.setattr(models, "_sleep", sleeps.append)
    monkeypatch.setattr(models, "_random", lambda: 1.0)
    return sleeps


# ---- Choosing a provider and model ----------------------------------------------

def test_default_provider_is_openai():
    llm = get_chat_model()
    assert isinstance(llm, ChatOpenAI)
    assert llm.temperature == 0.0
    assert llm.model_name == "gpt-6-luna"


def test_provider_from_env(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "gemini")
    assert isinstance(get_chat_model(), ChatGoogleGenerativeAI)


def test_argument_beats_env(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "gemini")
    assert isinstance(get_chat_model("openai"), ChatOpenAI)


def test_provider_name_is_case_insensitive():
    assert isinstance(get_chat_model(" Gemini "), ChatGoogleGenerativeAI)


def test_model_name_from_env_and_argument(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-from-env")
    assert get_chat_model("gemini").model.endswith("gemini-from-env")
    assert get_chat_model("gemini", model="gemini-from-arg").model.endswith("gemini-from-arg")


def test_builtin_default_model_names():
    assert get_chat_model("openai").model_name == models.PROVIDERS["openai"].default_model
    assert get_chat_model("gemini").model.endswith(models.PROVIDERS["gemini"].default_model)
    assert get_chat_model("mistral").model == models.PROVIDERS["mistral"].default_model


def test_mistral_is_available_but_not_a_fallback(monkeypatch):
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-from-env")
    llm = get_chat_model("mistral")
    assert isinstance(llm, ChatMistralAI)
    assert llm.model == "mistral-from-env"
    assert "mistral" not in models.FALLBACKS.values()


def test_unknown_provider():
    with pytest.raises(ModelConfigError, match="Choose one of: gemini, mistral, openai"):
        get_chat_model("claude")


@pytest.mark.parametrize("value", ["", "your-openai-key-here"])
def test_missing_or_placeholder_key(monkeypatch, value):
    monkeypatch.setenv("OPENAI_API_KEY", value)
    with pytest.raises(ModelConfigError, match="OPENAI_API_KEY is not set"):
        get_chat_model("openai")


def test_error_messages_never_contain_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(ModelConfigError) as excinfo:
        get_chat_model("openai")
    for key in (FAKE_GEMINI, FAKE_OPENAI, FAKE_MISTRAL):
        assert key not in str(excinfo.value)


@pytest.mark.parametrize("provider, key", [("openai", FAKE_OPENAI), ("gemini", FAKE_GEMINI), ("mistral", FAKE_MISTRAL)])
def test_key_is_not_shown_in_repr(provider, key):
    assert key not in repr(get_chat_model(provider))


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


# ---- Library retries off, ours on ---------------------------------------------------

@pytest.mark.parametrize("provider", ["openai", "gemini", "mistral"])
def test_library_retries_are_off_and_ours_are_on(provider):
    llm = get_chat_model(provider)
    assert llm.max_retries == 0
    assert llm.max_attempts == models.DEFAULT_MAX_ATTEMPTS


def test_retrying_class_keeps_the_provider_class_name():
    """Langfuse names each generation after the class, so it must still say ChatOpenAI."""
    assert type(get_chat_model("openai")).__name__ == "ChatOpenAI"


def test_max_attempts_from_env_and_argument(monkeypatch):
    monkeypatch.setenv("MODEL_MAX_ATTEMPTS", "6")
    assert get_chat_model().max_attempts == 6
    assert get_chat_model(max_attempts=2).max_attempts == 2


# ---- Fallback switch ------------------------------------------------------------------

def test_fallback_on_by_default(monkeypatch):
    monkeypatch.delenv("MODEL_FALLBACK")
    llm = get_chat_model()
    assert isinstance(llm.runnable, ChatOpenAI)
    assert [type(m) for m in llm.fallbacks] and isinstance(llm.fallbacks[0], ChatGoogleGenerativeAI)
    assert llm.fallbacks[0].metadata["fallback_for"] == "openai"


@pytest.mark.parametrize("value", ["off", "OFF", "false", "0", "no"])
def test_fallback_off_from_env(monkeypatch, value):
    monkeypatch.setenv("MODEL_FALLBACK", value)
    assert isinstance(get_chat_model(), ChatOpenAI)


def test_argument_beats_env_for_fallback(monkeypatch):
    monkeypatch.setenv("MODEL_FALLBACK", "on")
    assert isinstance(get_chat_model(fallback=False), ChatOpenAI)
    monkeypatch.setenv("MODEL_FALLBACK", "off")
    assert isinstance(get_chat_model(fallback=True).fallbacks[0], ChatGoogleGenerativeAI)


def test_missing_gemini_key_turns_fallback_off_with_a_warning(monkeypatch):
    monkeypatch.setenv("MODEL_FALLBACK", "on")
    monkeypatch.delenv("GOOGLE_API_KEY")
    with pytest.warns(UserWarning, match="fallback is off: GOOGLE_API_KEY is not set"):
        llm = get_chat_model()
    assert isinstance(llm, ChatOpenAI)


def test_forced_fallback_without_key_is_an_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY")
    with pytest.raises(ModelConfigError, match="GOOGLE_API_KEY"):
        get_chat_model(fallback=True)


def test_providers_without_a_fallback(monkeypatch):
    monkeypatch.setenv("MODEL_FALLBACK", "on")
    assert isinstance(get_chat_model("gemini"), ChatGoogleGenerativeAI)
    with pytest.raises(ModelConfigError, match="no fallback provider for 'gemini'"):
        get_chat_model("gemini", fallback=True)


def test_tracing_handler_goes_on_the_whole_chain(monkeypatch):
    monkeypatch.setattr(models, "tracing_configured", lambda: True)
    llm = get_chat_model(fallback=True)
    assert type(llm.config["callbacks"][0]).__name__ == "LangchainCallbackHandler"
    # The primary model keeps only the recorder, so the call is not traced twice.
    assert [type(h) for h in llm.bound.runnable.callbacks] == [models.FallbackRecorder]


# ---- Fake models ---------------------------------------------------------------------

class FakeChat(BaseChatModel):
    """A chat model that works through a script: each call takes the next item.
    An exception is raised; a string is returned as the reply. When the script
    is empty, it replies with `reply`."""

    reply: str = "ok"
    script: list[Any] = []
    calls: int = 0
    tokens: tuple[int, int] = (1000, 200)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        item = self.script.pop(0) if self.script else self.reply
        if isinstance(item, BaseException):
            raise item
        usage = {"input_tokens": self.tokens[0], "output_tokens": self.tokens[1], "total_tokens": sum(self.tokens)}
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=item, usage_metadata=usage))])

    @property
    def _llm_type(self) -> str:
        return "fake"


def rate_limited(headers: dict | None = None, message: str = "429 too many requests") -> ModelRateLimitError:
    """A 429 like LangChain raises, optionally with response headers (Retry-After)."""
    error = ModelRateLimitError(message)
    error.response = SimpleNamespace(headers=headers or {})
    return error


class FakeLangfuse:
    def __init__(self):
        self.events = []

    def create_event(self, **kwargs):
        self.events.append(kwargs)


@pytest.fixture
def fakes(monkeypatch):
    """Swap the OpenAI and Gemini builders for retrying fake models, and capture
    what would be sent to Langfuse. Set state["openai"] / state["gemini"] to a
    script list before calling get_chat_model()."""
    state = {"openai": [], "gemini": [], "built": {}, "trace_metadata": []}
    langfuse = FakeLangfuse()
    state["langfuse"] = langfuse

    def builder(provider_name):
        def build(model, api_key, temperature, timeout, metadata):
            fake = models._with_retries(FakeChat)(
                reply=f"from {provider_name}", script=list(state[provider_name]), metadata=metadata,
            )
            state["built"][provider_name] = fake
            return fake
        return build

    for name in ("openai", "gemini"):
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


# ---- Retries ---------------------------------------------------------------------------

def test_retry_then_success(fakes, fake_clock):
    fakes["openai"] = [rate_limited(), ModelAPIError("503 unavailable")]
    reply = get_chat_model(fallback=False).invoke("hello")
    assert reply.text == "from openai"
    assert fakes["built"]["openai"].calls == 3
    assert fake_clock == [1.0, 2.0]  # exponential backoff: 1s, then 2s
    assert reply.response_metadata["clewline"]["attempts"] == 3
    assert reply.response_metadata["clewline"]["waited_s"] == 3.0


def test_backoff_doubles_with_jitter_and_is_capped(monkeypatch):
    monkeypatch.setattr(models, "_random", lambda: 0.0)          # lowest jitter: x0.5
    assert [models.backoff_delay(n) for n in (1, 2, 3)] == [0.5, 1.0, 2.0]
    monkeypatch.setattr(models, "_random", lambda: 1.0)          # highest jitter: x1.0
    assert models.backoff_delay(10) == models.BACKOFF_CAP_S


def test_gives_up_after_max_attempts_with_a_clear_error(fakes, fake_clock):
    fakes["openai"] = [rate_limited()] * 10
    with pytest.raises(RetriesExhausted, match=r"openai/gpt-6-luna failed after 4 attempt\(s\) \(rate_limit\)"):
        get_chat_model(fallback=False).invoke("hello")
    assert fakes["built"]["openai"].calls == 4
    assert fake_clock == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    "headers, expected",
    [({"retry-after": "7"}, 7.0), ({"retry-after-ms": "1500"}, 1.5)],
)
def test_retry_after_header_is_honoured(fakes, fake_clock, headers, expected):
    fakes["openai"] = [rate_limited(headers)]
    get_chat_model(fallback=False).invoke("hello")
    assert fake_clock == [expected]


def test_retry_after_found_on_the_wrapped_provider_error(fakes, fake_clock):
    """LangChain raises its own error 'from' the SDK error; the headers can be on either."""
    inner = rate_limited({"retry-after": "3"})
    outer = ModelRateLimitError("429")
    outer.__cause__ = inner
    fakes["openai"] = [outer]
    get_chat_model(fallback=False).invoke("hello")
    assert fake_clock == [3.0]


def test_gemini_retry_delay_in_the_error_body_is_honoured(fakes, fake_clock):
    fakes["openai"] = [rate_limited(message="429 RESOURCE_EXHAUSTED {'retryDelay': '12s'}")]
    get_chat_model(fallback=False).invoke("hello")
    assert fake_clock == [12.0]


def test_retry_after_longer_than_the_limit_gives_up_at_once(fakes, fake_clock):
    fakes["openai"] = [rate_limited({"retry-after": "3600"})]
    with pytest.raises(RetriesExhausted, match="asked to wait 3600s"):
        get_chat_model(fallback=False).invoke("hello")
    assert fake_clock == []
    assert fakes["built"]["openai"].calls == 1


@pytest.mark.parametrize(
    "error",
    [ModelTimeoutError("timed out"), httpx.ReadTimeout("read timed out"),
     ModelConnectionError("refused"), httpx.ConnectError("refused")],
)
def test_timeouts_and_connection_errors_are_retried(fakes, fake_clock, error):
    fakes["openai"] = [error]
    assert get_chat_model(fallback=False).invoke("hello").text == "from openai"
    assert fake_clock == [1.0]


@pytest.mark.parametrize(
    "error",
    [ModelInvalidRequestError("400"), ModelAuthenticationError("401"),
     ModelPermissionDeniedError("403"), ModelNotFoundError("404"), ValueError("our bug")],
)
def test_never_retried(fakes, fake_clock, error):
    fakes["openai"] = [error]
    with pytest.raises(type(error)):
        get_chat_model(fallback=False).invoke("hello")
    assert fakes["built"]["openai"].calls == 1
    assert fake_clock == []


def test_retries_are_counted_in_the_run_budget(fakes):
    fakes["openai"] = [rate_limited(), rate_limited()]
    get_chat_model(fallback=False).invoke("hello")
    summary = models.current_budget().summary()["openai/gpt-6-luna"]
    assert summary["calls"] == 1 and summary["retries"] == 2 and summary["wait_s"] == 3.0


# ---- Spend cap ----------------------------------------------------------------------------

def test_cost_uses_the_price_table(fakes):
    get_chat_model(fallback=False).invoke("hello")  # 1000 in, 200 out at $0.10 / $0.50 per 1M
    assert models.current_budget().spent_usd == pytest.approx(0.0002)


def test_spend_cap_stops_before_the_next_call(fakes):
    models.start_run(max_cost_usd=0.0003)
    llm = get_chat_model(fallback=True)
    llm.invoke("one")                       # spends $0.0002
    llm.invoke("two")                       # spends $0.0002 -> $0.0004, over the cap
    with pytest.raises(SpendCapReached, match="Spend cap reached"):
        llm.invoke("three")                 # refused before it is sent
    assert fakes["built"]["openai"].calls == 2
    assert fakes["built"]["gemini"].calls == 0  # the cap never triggers the fallback


def test_spend_cap_from_env(monkeypatch):
    monkeypatch.setenv("MAX_RUN_COST_USD", "1.25")
    assert models.start_run().max_cost_usd == 1.25


def test_default_spend_cap_is_fifty_cents():
    assert models.start_run().max_cost_usd == 0.50


def test_unknown_model_price_is_costed_high_with_a_warning():
    with pytest.warns(UserWarning, match="No price for model 'mystery-model'"):
        cost = models.call_cost("mystery-model", 1_000_000, 0)
    assert cost == models.UNKNOWN_PRICE[0]


def test_resumed_run_counts_earlier_spend():
    budget = models.start_run(max_cost_usd=0.50, already_spent_usd=0.50)
    with pytest.raises(SpendCapReached):
        budget.check()


# ---- Fallback behaviour ----------------------------------------------------------------

@pytest.mark.parametrize(
    "error, reason",
    [
        (rate_limited(), "rate_limit"),
        (ModelAPIError("503 service unavailable"), "server_error"),
        (ModelTimeoutError("request timed out"), "timeout"),
        (httpx.ConnectError("connection refused"), "connection_error"),
    ],
)
def test_failure_after_retries_falls_back_to_gemini_and_is_recorded(fakes, error, reason):
    fakes["openai"] = [error] * 4
    reply = get_chat_model(fallback=True).invoke("hello")

    assert reply.text == "from gemini"
    assert fakes["built"]["openai"].calls == 4    # retried first ...
    assert fakes["built"]["gemini"].calls == 1    # ... then fell back
    assert reply.response_metadata["clewline"]["provider"] == "gemini"

    [event] = fakes["langfuse"].events
    assert event["name"] == "model_fallback"
    assert event["level"] == "WARNING"
    assert event["metadata"]["fallback_from"] == "openai/gpt-6-luna"
    assert event["metadata"]["fallback_to"] == "gemini/gemini-3.8-flash"
    assert event["metadata"]["fallback_reason"] == reason
    assert event["metadata"]["fallback_error"].startswith("RetriesExhausted: openai/gpt-6-luna failed after 4")
    assert fakes["trace_metadata"] == [event["metadata"]]


def test_answering_model_is_labelled_as_gemini(fakes):
    fakes["openai"] = [rate_limited()] * 4
    get_chat_model(fallback=True).invoke("hello")
    openai, gemini = fakes["built"]["openai"].metadata, fakes["built"]["gemini"].metadata
    assert openai["provider"] == "openai" and "fallback_for" not in openai
    assert gemini["provider"] == "gemini" and gemini["fallback_for"] == "openai"


def test_no_fallback_when_openai_answers_after_a_retry(fakes):
    fakes["openai"] = [rate_limited()]
    assert get_chat_model(fallback=True).invoke("hello").text == "from openai"
    assert fakes["built"]["gemini"].calls == 0
    assert fakes["langfuse"].events == []


@pytest.mark.parametrize("error", [ModelInvalidRequestError("400"), ModelAuthenticationError("401"), ValueError("bug")])
def test_other_errors_do_not_fall_back(fakes, error):
    fakes["openai"] = [error]
    with pytest.raises(type(error)):
        get_chat_model(fallback=True).invoke("hello")
    assert fakes["built"]["gemini"].calls == 0
    assert fakes["langfuse"].events == []


def test_bad_output_does_not_fall_back(fakes):
    fakes["openai"] = ["this is not JSON"]
    chain = get_chat_model(fallback=True) | JsonOutputParser()
    with pytest.raises(OutputParserException):
        chain.invoke("give me JSON")
    assert fakes["built"]["gemini"].calls == 0


def test_with_fallback_off_a_call_failure_is_raised(fakes):
    """Evaluation runs: the failure surfaces as an error, so it can be counted as one."""
    fakes["openai"] = [rate_limited()] * 4
    with pytest.raises(models.CALL_FAILURES):
        get_chat_model(fallback=False).invoke("hello")
    assert "gemini" not in fakes["built"]
    assert fakes["langfuse"].events == []


def test_long_error_messages_are_cut_to_fit_langfuse(fakes):
    fakes["openai"] = [ModelAPIError("x" * 500)] * 4
    get_chat_model(fallback=True).invoke("hello")
    assert len(fakes["langfuse"].events[0]["metadata"]["fallback_error"]) == 150
