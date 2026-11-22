"""Live smoke test: one real call per provider, traced in Langfuse.

Skipped in normal runs. Run with:   uv run pytest -m live -s
A provider whose key is not set in .env is skipped, not failed.
"""

import pytest

from core.models import ModelConfigError, get_chat_model
from core.tracing import flush, observe

pytestmark = pytest.mark.live


@observe(name="live_model_smoke_test")
def ask(provider: str) -> str:
    llm = get_chat_model(provider)
    reply = llm.invoke("Reply with exactly one word: ready")
    return reply.text  # .text joins the reply's text parts into one string


@pytest.mark.parametrize("provider", ["gemini", "openai"])
def test_live_call(provider):
    try:
        answer = ask(provider)
    except ModelConfigError as error:
        pytest.skip(str(error))
    finally:
        flush()
    print(f"\n{provider} replied: {answer!r}")
    assert "ready" in answer.lower()
