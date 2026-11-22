"""F4. One function to get a chat model from any supported provider.

    from core.models import get_chat_model

    llm = get_chat_model()                    # provider from .env (default: gemini)
    llm = get_chat_model("openai")            # same code, another provider
    reply = llm.invoke("Hello")               # reply.text is the text

Every model returned here is already connected to Langfuse (when tracing is
configured), so each call is recorded with its prompt, reply, tokens and
cost. Governance rule 2 is met without any extra code in the steps.

Fallback: when Gemini's call fails (rate limit, timeout, server error), the
same request goes to Mistral instead. Bad requests, wrong keys and bad output
never trigger it, because another model would not fix them. Each fallback is
written into the trace with its reason. It is ON by default and OFF in
evaluation runs, so every score comes from one model.

Settings come from .env:
    MODEL_PROVIDER   gemini | openai | mistral   (default: gemini)
    MODEL_FALLBACK   on | off                    (default: on)
    GEMINI_MODEL     e.g. gemini-3.8-flash
    OPENAI_MODEL     e.g. gpt-5-mini
    MISTRAL_MODEL    e.g. mistral-small-2603
    GOOGLE_API_KEY   / OPENAI_API_KEY / MISTRAL_API_KEY
"""

import os
import warnings
from dataclasses import dataclass
from typing import Callable

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.exceptions import (
    ModelAPIError,
    ModelConnectionError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langfuse import propagate_attributes

from core.tracing import get_langchain_handler, get_langfuse, tracing_configured  # also loads .env

DEFAULT_PROVIDER = "gemini"

# Which provider takes over when another one's call fails.
FALLBACKS: dict[str, str] = {"gemini": "mistral"}

# Call failures: the request got no answer, so another provider might give one.
# LangChain maps each provider's HTTP errors to these shared types. Timeouts and
# dropped connections can still arrive as raw httpx errors, so those are listed too.
# Not here on purpose: bad requests (400), wrong keys (401/403), unknown model (404)
# and output that fails to parse. Another model would not fix those.
CALL_FAILURES: tuple[type[BaseException], ...] = (
    ModelRateLimitError,     # 429
    ModelAPIError,           # 5xx
    ModelTimeoutError,
    ModelConnectionError,
    httpx.TimeoutException,
    httpx.NetworkError,
)


class ModelConfigError(RuntimeError):
    """Raised when a provider is unknown or its key is missing. Never contains the key."""


# ---- Providers -------------------------------------------------------------

def _build_gemini(model, api_key, temperature, timeout, max_retries, metadata) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model, google_api_key=api_key, temperature=temperature,
        timeout=timeout, max_retries=max_retries, metadata=metadata,
    )


def _build_openai(model, api_key, temperature, timeout, max_retries, metadata) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model, api_key=api_key, temperature=temperature,
        timeout=timeout, max_retries=max_retries, metadata=metadata,
    )


def _build_mistral(model, api_key, temperature, timeout, max_retries, metadata) -> BaseChatModel:
    from langchain_mistralai import ChatMistralAI

    return ChatMistralAI(
        model=model, api_key=api_key, temperature=temperature,
        timeout=int(timeout), max_retries=max_retries, metadata=metadata,
    )


@dataclass(frozen=True)
class Provider:
    key_env: str           # which .env variable holds the API key
    model_env: str         # which .env variable holds the model name
    default_model: str     # used when model_env is not set
    build: Callable[..., BaseChatModel]


# To add a provider (for example Groq), add one entry here and one builder above.
PROVIDERS: dict[str, Provider] = {
    "gemini": Provider("GOOGLE_API_KEY", "GEMINI_MODEL", "gemini-3.8-flash", _build_gemini),
    "openai": Provider("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-5-mini", _build_openai),
    # Mistral Small 4 (v26.03), pinned. Mistral warns that "-latest" aliases can
    # change behaviour and price silently, which would break eval comparisons.
    "mistral": Provider("MISTRAL_API_KEY", "MISTRAL_MODEL", "mistral-small-2603", _build_mistral),
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
    return config.build(model=model_name, api_key=api_key, metadata=metadata, **settings)


# ---- Fallback --------------------------------------------------------------

def fallback_enabled() -> bool:
    """MODEL_FALLBACK from .env. On unless set to off/false/0/no."""
    return os.getenv("MODEL_FALLBACK", "on").strip().lower() not in {"off", "false", "0", "no"}


def failure_reason(error: BaseException) -> str:
    """A short label for why a call failed: rate_limit, timeout, server_error or connection_error."""
    if isinstance(error, ModelRateLimitError):
        return "rate_limit"
    if isinstance(error, (ModelTimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(error, ModelAPIError):
        return "server_error"
    return "connection_error"


def record_fallback(primary: dict, backup: dict, error: BaseException) -> dict:
    """Write the fallback into the current trace, and return what was written.

    Two records, so it is easy to find:
      - an event called "model_fallback" (level WARNING) in the trace tree
      - trace metadata (fallback_from, fallback_to, fallback_reason), which you can filter on
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
        with propagate_attributes(metadata=details):  # sets it on the active span, and so on the trace
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
        return _build(backup_name, None, settings, extra_metadata={"fallback_for": name})
    except ModelConfigError as error:
        if fallback:
            raise
        warnings.warn(f"Model fallback is off: {error}")
        return None


# ---- The one function steps call -------------------------------------------

def get_chat_model(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    timeout: float = 60,
    max_retries: int = 2,
    fallback: bool | None = None,
) -> BaseChatModel | Runnable:
    """Return a LangChain chat model for the chosen provider.

    provider     "gemini", "openai" or "mistral". Default: MODEL_PROVIDER from .env, then "gemini".
    model        model name. Default: GEMINI_MODEL / OPENAI_MODEL / MISTRAL_MODEL, then a built-in default.
    temperature  0.0 by default, so runs are as repeatable as possible for evaluation.
    fallback     True / False to force it. None (default) follows MODEL_FALLBACK in .env.
                 Only providers listed in FALLBACKS have one (today: gemini -> mistral).

    Without a fallback this returns the provider's chat model itself. With one,
    it returns a LangChain "runnable with fallbacks", which you use the same way:
    .invoke(), .with_structured_output() and .bind_tools() all work.
    """
    name = (provider or os.getenv("MODEL_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if name not in PROVIDERS:
        raise ModelConfigError(f"Unknown provider '{name}'. Choose one of: {', '.join(sorted(PROVIDERS))}.")

    settings = {"temperature": temperature, "timeout": timeout, "max_retries": max_retries}
    primary = _build(name, model, settings)
    backup = _build_backup(name, fallback, settings)

    if backup is None:
        if tracing_configured():
            primary.callbacks = [get_langchain_handler()]
        return primary

    primary.callbacks = [FallbackRecorder(primary.metadata, backup.metadata)]
    # with_fallbacks: try `primary`; if it raises one of CALL_FAILURES, send the
    # same input to `backup`. Any other error is raised as normal.
    chain = primary.with_fallbacks([backup], exceptions_to_handle=CALL_FAILURES)
    if tracing_configured():
        # Handler on the whole chain, so the failed call, the fallback event and
        # the answering call all land in one trace.
        chain = chain.with_config(callbacks=[get_langchain_handler()])
    return chain
