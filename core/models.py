"""F4. One function to get a chat model from any supported provider.

    from core.models import get_chat_model

    llm = get_chat_model()                    # provider from .env (default: gemini)
    llm = get_chat_model("openai")            # same code, another provider
    reply = llm.invoke("Hello")               # reply.content is the text

Every model returned here is already connected to Langfuse (when tracing is
configured), so each call is recorded with its prompt, reply, tokens and
cost. Governance rule 2 is met without any extra code in the steps.

Settings come from .env:
    MODEL_PROVIDER   gemini | openai           (default: gemini)
    GEMINI_MODEL     e.g. gemini-3.8-flash
    OPENAI_MODEL     e.g. gpt-5-mini
    GOOGLE_API_KEY   / OPENAI_API_KEY
"""

import os
from dataclasses import dataclass
from typing import Callable

from langchain_core.language_models.chat_models import BaseChatModel

from core.tracing import get_langchain_handler, tracing_configured  # also loads .env

DEFAULT_PROVIDER = "gemini"


class ModelConfigError(RuntimeError):
    """Raised when a provider is unknown or its key is missing. Never contains the key."""


def _build_gemini(model: str, api_key: str, temperature: float, timeout: float, max_retries: int, callbacks) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
        callbacks=callbacks,
    )


def _build_openai(model: str, api_key: str, temperature: float, timeout: float, max_retries: int, callbacks) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
        callbacks=callbacks,
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
}


def _read_key(provider_name: str, env_name: str) -> str:
    key = os.getenv(env_name, "").strip()
    if not key or key.startswith("your-"):  # empty, or still the .env.example placeholder
        raise ModelConfigError(f"{env_name} is not set in .env, so the '{provider_name}' provider cannot be used.")
    return key


def get_chat_model(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    timeout: float = 60,
    max_retries: int = 2,
) -> BaseChatModel:
    """Return a LangChain chat model for the chosen provider.

    provider     "gemini" or "openai". Default: MODEL_PROVIDER from .env, then "gemini".
    model        model name. Default: GEMINI_MODEL / OPENAI_MODEL from .env, then a built-in default.
    temperature  0.0 by default, so runs are as repeatable as possible for evaluation.
    """
    name = (provider or os.getenv("MODEL_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if name not in PROVIDERS:
        raise ModelConfigError(f"Unknown provider '{name}'. Choose one of: {', '.join(sorted(PROVIDERS))}.")

    config = PROVIDERS[name]
    api_key = _read_key(name, config.key_env)
    model_name = model or os.getenv(config.model_env) or config.default_model
    callbacks = [get_langchain_handler()] if tracing_configured() else None

    return config.build(
        model=model_name,
        api_key=api_key,
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
        callbacks=callbacks,
    )
