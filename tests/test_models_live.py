"""Live smoke test: one real call per provider, traced in Langfuse.

Skipped in normal runs. Run with:   uv run pytest -m live -s
A provider whose key is not set in .env is skipped, not failed.
The fallback is off here, so a pass means that provider itself answered.
"""

import pytest

from core.models import ModelConfigError, get_chat_model
from core.tracing import flush, observe

pytestmark = pytest.mark.live


@observe(name="live_model_smoke_test")
def ask(provider: str):
    llm = get_chat_model(provider, fallback=False)
    return llm.invoke("Reply with exactly one word: ready")


@pytest.mark.parametrize("provider", ["gemini", "openai", "mistral"])
def test_live_call(provider):
    try:
        reply = ask(provider)
    except ModelConfigError as error:
        pytest.skip(str(error))
    finally:
        flush()
    answered_by = reply.response_metadata.get("model_name") or reply.response_metadata.get("model")
    print(f"\n{provider} ({answered_by}) replied: {reply.text!r}")  # .text joins the reply's text parts
    assert "ready" in reply.text.lower()
