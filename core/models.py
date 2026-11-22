"""F4. One function to get a chat model from any supported provider.

    from core.models import get_chat_model

    llm = get_chat_model()                    # provider from .env (default: openai)
    llm = get_chat_model("gemini")            # same code, another provider
    reply = llm.invoke("Hello")               # reply.text is the text

Every model returned here:
  - is connected to Langfuse (when tracing is configured), so each call is
    recorded with its prompt, reply, tokens and cost (governance rule 2);
  - retries 429s, 5xx errors and timeouts itself, with backoff and Retry-After.
    The provider libraries' own retries are switched off, so only ours run;
  - counts its cost against a spend cap (MAX_RUN_COST_USD, default $0.50);
  - falls back from OpenAI to Gemini when a call still fails after retries.
    Bad requests, wrong keys and bad output never trigger the fallback.
    It is OFF in evaluation runs, so every score comes from one model.

Settings come from .env:
    MODEL_PROVIDER     openai | gemini | mistral   (default: openai)
    MODEL_FALLBACK     on | off                    (default: on)
    OPENAI_MODEL / GEMINI_MODEL / MISTRAL_MODEL
    OPENAI_API_KEY / GOOGLE_API_KEY / MISTRAL_API_KEY
    MODEL_MAX_ATTEMPTS (default 4)   MAX_RUN_COST_USD (default 0.50)
"""

import asyncio
import os
import random
import re
import time
import warnings
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from functools import cache
from typing import Callable

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.exceptions import (
    ModelAPIError,
    ModelConnectionError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langfuse import propagate_attributes

from core.tracing import get_langchain_handler, get_langfuse, tracing_configured  # also loads .env

DEFAULT_PROVIDER = "openai"

# Which provider takes over when another one's call still fails after retries.
# Mistral is available as a provider but is not in the fallback path.
FALLBACKS: dict[str, str] = {"openai": "gemini"}

# ---- Retry settings ----------------------------------------------------------
DEFAULT_MAX_ATTEMPTS = 4      # first try + 3 retries
BACKOFF_BASE_S = 1.0          # waits grow 1s, 2s, 4s ... (before jitter)
BACKOFF_CAP_S = 30.0          # never wait longer than this between tries
MAX_RETRY_AFTER_S = 60.0      # if the server asks us to wait longer, give up instead

# Errors worth trying again: the request got no answer, and a later try might.
# LangChain maps each provider's HTTP errors to these shared types. Timeouts and
# dropped connections can also arrive as raw httpx errors, so those are listed too.
# Never retried: 400 (bad request), 401/403 (key), 404 (model), unparseable output.
RETRYABLE: tuple[type[BaseException], ...] = (
    ModelRateLimitError,     # 429
    ModelAPIError,           # 5xx, including 503
    ModelTimeoutError,
    ModelConnectionError,
    httpx.TimeoutException,
    httpx.NetworkError,
)

# ---- Spend cap ---------------------------------------------------------------
DEFAULT_MAX_RUN_COST_USD = 0.50

# List prices in USD per 1M tokens: (input, output). Checked 2026-11-22.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-6-luna": (0.10, 0.50),           # developers.openai.com/api/docs/pricing
    "mistral-small-2603": (0.15, 0.60),   # docs.mistral.ai/models/mistral-small-4-0-26-03
    # Not on a Google page we could read; worked out from the cost Langfuse's own
    # price table gave our live call. Free-tier calls are not actually charged.
    "gemini-3.8-flash": (0.75, 3.75),
}
# A model missing from PRICES is costed at this deliberately high price, so the
# spend cap still protects you. A warning names the model.
UNKNOWN_PRICE: tuple[float, float] = (2.00, 10.00)

# Swapped for fakes in tests, so no test ever really sleeps.
_sleep = time.sleep
_async_sleep = asyncio.sleep
_random = random.random


class ModelConfigError(RuntimeError):
    """Raised when a provider is unknown or its key is missing. Never contains the key."""


class RetriesExhausted(ModelError):
    """A call kept failing (429, 5xx, timeout) and we stopped trying.

    In normal use this triggers the fallback. In an evaluation run it is
    counted as an error, not as a wrong answer.
    """

    def __init__(self, provider: str, model: str, attempts: int, reason: str, detail: str):
        self.provider, self.model, self.attempts, self.reason = provider, model, attempts, reason
        super().__init__(f"{provider}/{model} failed after {attempts} attempt(s) ({reason}): {detail}")


class SpendCapReached(RuntimeError):
    """The run has spent MAX_RUN_COST_USD. Raised before a call, so nothing more is spent."""


# Everything that means "this call got no answer": triggers the fallback.
CALL_FAILURES: tuple[type[BaseException], ...] = (*RETRYABLE, RetriesExhausted)


# ---- Spend tracking ------------------------------------------------------------

@dataclass
class CallRecord:
    """One model call as the spend tracker saw it (after all its retries)."""

    provider: str
    model: str
    attempts: int
    waited_s: float
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    ok: bool = True
    error: str | None = None


@dataclass
class RunBudget:
    """Counts spend for one run and refuses new calls once the cap is reached."""

    max_cost_usd: float
    already_spent_usd: float = 0.0        # from earlier sessions of a resumed run
    records: list[CallRecord] = field(default_factory=list)

    @property
    def spent_usd(self) -> float:
        return self.already_spent_usd + sum(r.cost_usd for r in self.records)

    def check(self) -> None:
        if self.spent_usd >= self.max_cost_usd:
            raise SpendCapReached(
                f"Spend cap reached: ${self.spent_usd:.4f} of ${self.max_cost_usd:.2f} "
                "(MAX_RUN_COST_USD). No further model calls in this run."
            )

    def summary(self) -> dict:
        """Totals per provider/model, for reports."""
        out: dict[str, dict] = {}
        for r in self.records:
            row = out.setdefault(f"{r.provider}/{r.model}", {
                "calls": 0, "retries": 0, "failed_after_retries": 0, "wait_s": 0.0,
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            })
            row["calls"] += 1
            row["retries"] += r.attempts - 1
            row["failed_after_retries"] += 0 if r.ok else 1
            row["wait_s"] += r.waited_s
            row["input_tokens"] += r.input_tokens
            row["output_tokens"] += r.output_tokens
            row["cost_usd"] += r.cost_usd
        return out


def _env_cap() -> float:
    return float(os.getenv("MAX_RUN_COST_USD") or DEFAULT_MAX_RUN_COST_USD)


_budget: RunBudget | None = None


def start_run(max_cost_usd: float | None = None, already_spent_usd: float = 0.0) -> RunBudget:
    """Begin a new run with a fresh budget. The evaluation runner calls this."""
    global _budget
    _budget = RunBudget(max_cost_usd if max_cost_usd is not None else _env_cap(), already_spent_usd)
    return _budget


def current_budget() -> RunBudget:
    """The budget for this process. A script that never calls start_run() gets one run."""
    if _budget is None:
        start_run()
    return _budget


def call_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICES:
        warnings.warn(f"No price for model '{model}'; costing it at the high fallback price {UNKNOWN_PRICE}.")
    price_in, price_out = PRICES.get(model, UNKNOWN_PRICE)
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


# ---- Retries -------------------------------------------------------------------

def failure_reason(error: BaseException) -> str:
    """A short label for why a call failed: rate_limit, timeout, server_error or connection_error."""
    if isinstance(error, RetriesExhausted):
        return error.reason
    if isinstance(error, ModelRateLimitError):
        return "rate_limit"
    if isinstance(error, (ModelTimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(error, ModelAPIError):
        return "server_error"
    return "connection_error"


def _error_chain(error: BaseException):
    """The error and the errors that caused it (LangChain wraps the provider's error)."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def retry_after_seconds(error: BaseException) -> float | None:
    """How long the server asked us to wait, if it said.

    Reads the Retry-After header (seconds or an HTTP date), OpenAI's
    retry-after-ms header, and Gemini's "retryDelay" in the error body.
    """
    for e in _error_chain(error):
        headers = getattr(getattr(e, "response", None), "headers", None)
        if headers:
            if headers.get("retry-after-ms"):
                try:
                    return float(headers["retry-after-ms"]) / 1000
                except ValueError:
                    pass
            value = headers.get("retry-after")
            if value:
                try:
                    return float(value)
                except ValueError:
                    try:
                        when = parsedate_to_datetime(value)
                        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
                    except (TypeError, ValueError):
                        pass
        match = re.search(r"retryDelay['\"]?\s*:\s*['\"](\d+(?:\.\d+)?)s", str(e))
        if match:
            return float(match.group(1))
    return None


def backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter: 1s, 2s, 4s ... capped at 30s, each times 0.5 to 1.0.

    The jitter spreads retries out, so many waiting calls do not all hit the
    server again at the same moment.
    """
    return min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (attempt - 1)) * (0.5 + _random() / 2)


def _plan_retry(error: BaseException, attempt: int, max_attempts: int) -> tuple[float | None, str]:
    """(seconds to wait, note). None means give up now."""
    if attempt >= max_attempts:
        return None, "no attempts left"
    asked = retry_after_seconds(error)
    if asked is not None:
        if asked > MAX_RETRY_AFTER_S:
            return None, f"server asked to wait {asked:.0f}s, more than the {MAX_RETRY_AFTER_S:.0f}s limit"
        return asked, "retry-after"
    return backoff_delay(attempt), "backoff"


def _usage(result) -> tuple[int, int]:
    usage = getattr(result.generations[0].message, "usage_metadata", None) or {}
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def _finish(model, result, attempts: int, waited: float):
    """Record a successful call: cost, retries and waits go on the reply and in the budget."""
    provider, name = model.metadata["provider"], model.metadata["model"]
    tokens_in, tokens_out = _usage(result)
    cost = call_cost(name, tokens_in, tokens_out)
    current_budget().records.append(CallRecord(provider, name, attempts, waited, cost, tokens_in, tokens_out))
    for generation in result.generations:
        # Shows up with the reply in Langfuse, next to the call it describes.
        generation.message.response_metadata["clewline"] = {
            "provider": provider, "model": name, "attempts": attempts,
            "waited_s": round(waited, 3), "cost_usd": round(cost, 6),
        }
    return result


def _give_up(model, error: BaseException, attempts: int, waited: float, note: str) -> RetriesExhausted:
    provider, name = model.metadata["provider"], model.metadata["model"]
    reason = failure_reason(error)
    current_budget().records.append(CallRecord(provider, name, attempts, waited, ok=False, error=reason))
    detail = f"{type(error).__name__}: {error}"[:300]
    return RetriesExhausted(provider, name, attempts, reason, f"{detail} [{note}]")


@cache
def _with_retries(base: type[BaseChatModel]) -> type[BaseChatModel]:
    """A subclass of a LangChain chat model class that adds our retry loop and spend cap.

    It overrides _generate, the one method every call goes through, so
    .invoke(), .with_structured_output() and .bind_tools() all get retries.
    The class keeps its original name, so Langfuse still shows "ChatOpenAI".
    """

    class WithRetries(base):
        max_attempts: int = DEFAULT_MAX_ATTEMPTS

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            waited = 0.0
            for attempt in range(1, self.max_attempts + 1):
                current_budget().check()
                try:
                    result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                except RETRYABLE as error:
                    delay, note = _plan_retry(error, attempt, self.max_attempts)
                    if delay is None:
                        raise _give_up(self, error, attempt, waited, note) from error
                    _sleep(delay)
                    waited += delay
                    continue
                return _finish(self, result, attempt, waited)

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            waited = 0.0
            for attempt in range(1, self.max_attempts + 1):
                current_budget().check()
                try:
                    result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
                except RETRYABLE as error:
                    delay, note = _plan_retry(error, attempt, self.max_attempts)
                    if delay is None:
                        raise _give_up(self, error, attempt, waited, note) from error
                    await _async_sleep(delay)
                    waited += delay
                    continue
                return _finish(self, result, attempt, waited)

    WithRetries.__name__ = WithRetries.__qualname__ = base.__name__
    return WithRetries


# ---- Providers -------------------------------------------------------------------
# Every builder sets the library's own max_retries to 0, so only our loop retries.

def _build_openai(model, api_key, temperature, timeout, metadata) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return _with_retries(ChatOpenAI)(
        model=model, api_key=api_key, temperature=temperature,
        timeout=timeout, max_retries=0, metadata=metadata,
    )


def _build_gemini(model, api_key, temperature, timeout, metadata) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return _with_retries(ChatGoogleGenerativeAI)(
        model=model, google_api_key=api_key, temperature=temperature,
        timeout=timeout, max_retries=0, metadata=metadata,  # google-genai reads 0 as "one attempt"
    )


def _build_mistral(model, api_key, temperature, timeout, metadata) -> BaseChatModel:
    from langchain_mistralai import ChatMistralAI

    return _with_retries(ChatMistralAI)(
        model=model, api_key=api_key, temperature=temperature,
        timeout=int(timeout), max_retries=0, metadata=metadata,
    )


@dataclass(frozen=True)
class Provider:
    key_env: str           # which .env variable holds the API key
    model_env: str         # which .env variable holds the model name
    default_model: str     # used when model_env is not set
    build: Callable[..., BaseChatModel]


# To add a provider, add one entry here and one builder above.
PROVIDERS: dict[str, Provider] = {
    # Cheapest current OpenAI model with structured outputs (checked 2026-11-22).
    # gpt-5-nano and gpt-5-mini are cheaper or familiar, but shut down on 11 Dec 2026.
    "openai": Provider("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-6-luna", _build_openai),
    "gemini": Provider("GOOGLE_API_KEY", "GEMINI_MODEL", "gemini-3.8-flash", _build_gemini),
    # Ministral 3 8B, pinned. Mistral warns that "-latest" aliases can change
    # behaviour and price silently. On the free plan, mistral-small-2603 is
    # allowed 0 requests a minute; ministral-8b-2512 is allowed 2 (headers, 2026-11-22).
    "mistral": Provider("MISTRAL_API_KEY", "MISTRAL_MODEL", "ministral-8b-2512", _build_mistral),
}


def _read_key(provider_name: str, env_name: str) -> str:
    key = os.getenv(env_name, "").strip()
    if not key or key.startswith("your-"):  # empty, or still the .env.example placeholder
        raise ModelConfigError(f"{env_name} is not set in .env, so the '{provider_name}' provider cannot be used.")
    return key


def _build(name: str, model: str | None, settings: dict, extra_metadata: dict | None = None) -> BaseChatModel:
    config = PROVIDERS[name]
    api_key = _read_key(name, config.key_env)
    model_name = model or os.getenv(config.model_env) or config.default_model
    # LangChain passes this metadata to every callback, so Langfuse shows it on
    # each generation: the trace always says which provider and model ran.
    metadata = {"provider": name, "model": model_name, **(extra_metadata or {})}
    max_attempts = settings.pop("max_attempts")
    llm = config.build(model=model_name, api_key=api_key, metadata=metadata, **settings)
    llm.max_attempts = max_attempts
    return llm


# ---- Fallback --------------------------------------------------------------------

def fallback_enabled() -> bool:
    """MODEL_FALLBACK from .env. On unless set to off/false/0/no."""
    return os.getenv("MODEL_FALLBACK", "on").strip().lower() not in {"off", "false", "0", "no"}


def record_fallback(primary: dict, backup: dict, error: BaseException) -> dict:
    """Write the fallback into the current trace, and return what was written.

    Two records, so it is easy to find:
      - an event called "model_fallback" (level WARNING) in the trace tree
      - fallback_from / fallback_to / fallback_reason metadata on the active span
    """
    details = {
        "fallback_from": f"{primary['provider']}/{primary['model']}",
        "fallback_to": f"{backup['provider']}/{backup['model']}",
        "fallback_reason": failure_reason(error),
        "fallback_error": f"{type(error).__name__}: {error}"[:150],  # Langfuse caps metadata values at 200
    }
    if tracing_configured():
        get_langfuse().create_event(
            name="model_fallback", metadata=details, level="WARNING",
            status_message=f"{details['fallback_from']} failed ({details['fallback_reason']}), "
                           f"{details['fallback_to']} answered instead",
        )
        with propagate_attributes(metadata=details):  # sets it on the active span
            pass
    return details


class FallbackRecorder(BaseCallbackHandler):
    """Attached to the primary model only. LangChain calls on_llm_error when that
    model's call raises. If the error is a call failure, the fallback is about to
    run, so we record it in the trace."""

    def __init__(self, primary: dict, backup: dict):
        self.primary = primary
        self.backup = backup

    def on_llm_error(self, error: BaseException, **kwargs) -> None:
        if isinstance(error, CALL_FAILURES):
            record_fallback(self.primary, self.backup, error)


def _build_backup(name: str, fallback: bool | None, settings: dict) -> BaseChatModel | None:
    """The fallback model for this provider, or None if there should be no fallback."""
    wanted = fallback_enabled() if fallback is None else fallback
    if not wanted:
        return None
    backup_name = FALLBACKS.get(name)
    if backup_name is None:
        if fallback:  # asked for explicitly, so say it cannot be done
            raise ModelConfigError(f"There is no fallback provider for '{name}'.")
        return None
    try:
        return _build(backup_name, None, dict(settings), extra_metadata={"fallback_for": name})
    except ModelConfigError as error:
        if fallback:
            raise
        warnings.warn(f"Model fallback is off: {error}")
        return None


# ---- The one function steps call -------------------------------------------------

def get_chat_model(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    timeout: float = 60,
    max_attempts: int | None = None,
    fallback: bool | None = None,
) -> BaseChatModel | Runnable:
    """Return a LangChain chat model for the chosen provider.

    provider      "openai", "gemini" or "mistral". Default: MODEL_PROVIDER from .env, then "openai".
    model         model name. Default: OPENAI_MODEL / GEMINI_MODEL / MISTRAL_MODEL, then a built-in default.
    temperature   0.0 by default, so runs are as repeatable as possible for evaluation.
    max_attempts  tries per call, including the first. Default: MODEL_MAX_ATTEMPTS, then 4.
    fallback      True / False to force it. None (default) follows MODEL_FALLBACK in .env.
                  Only providers listed in FALLBACKS have one (today: openai -> gemini).

    Without a fallback this returns the provider's chat model itself. With one,
    it returns a LangChain "runnable with fallbacks", which you use the same way:
    .invoke(), .with_structured_output() and .bind_tools() all work.
    """
    name = (provider or os.getenv("MODEL_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if name not in PROVIDERS:
        raise ModelConfigError(f"Unknown provider '{name}'. Choose one of: {', '.join(sorted(PROVIDERS))}.")

    attempts = max_attempts or int(os.getenv("MODEL_MAX_ATTEMPTS") or DEFAULT_MAX_ATTEMPTS)
    settings = {"temperature": temperature, "timeout": timeout, "max_attempts": max(1, attempts)}
    primary = _build(name, model, dict(settings))
    backup = _build_backup(name, fallback, settings)

    if backup is None:
        if tracing_configured():
            primary.callbacks = [get_langchain_handler()]
        return primary

    primary.callbacks = [FallbackRecorder(primary.metadata, backup.metadata)]
    # with_fallbacks: try `primary`; if it raises one of CALL_FAILURES, send the
    # same input to `backup`. Any other error (including SpendCapReached) is raised.
    chain = primary.with_fallbacks([backup], exceptions_to_handle=CALL_FAILURES)
    if tracing_configured():
        # Handler on the whole chain, so the failed call, the fallback event and
        # the answering call all land in one trace.
        chain = chain.with_config(callbacks=[get_langchain_handler()])
    return chain
