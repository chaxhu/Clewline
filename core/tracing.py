"""F3. Tracing with Langfuse.

How to use it in any step:

    from core.tracing import observe

    @observe()
    def my_step(case):
        ...

Each call to a decorated function is recorded in Langfuse with its inputs,
outputs and timing. When a decorated function calls another decorated
function, the inner one appears nested under the outer one in the UI.

Keys and the server address come from .env:
    LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL
If they are missing, the code still runs. Nothing is sent, and a single
warning is printed.
"""

import os
import warnings

from dotenv import load_dotenv

# Load .env into os.environ before Langfuse reads its settings.
# Values that are already set (for example by tests) win over .env.
load_dotenv()

from langfuse import get_client, observe  # noqa: E402

__all__ = ["observe", "get_langfuse", "flush", "tracing_configured", "check_connection", "get_langchain_handler"]

REQUIRED_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")

_warned = False


def tracing_configured() -> bool:
    """True if every Langfuse setting is present in the environment."""
    return all(os.getenv(name) for name in REQUIRED_VARS)


def get_langfuse():
    """Return the shared Langfuse client, warning once if it is not configured."""
    global _warned
    if not tracing_configured() and not _warned:
        missing = [n for n in REQUIRED_VARS if not os.getenv(n)]
        warnings.warn(f"Langfuse tracing is not configured (missing: {', '.join(missing)}). Traces will not be sent.")
        _warned = True
    return get_client()


def check_connection() -> bool:
    """Ask the Langfuse server whether our keys are valid. Makes one network call."""
    if not tracing_configured():
        return False
    try:
        return get_langfuse().auth_check()
    except Exception:
        return False


def flush() -> None:
    """Send any traces still waiting in the background queue.

    The SDK sends traces in batches on a background thread. Short scripts
    must call this before exiting, or the last traces can be lost.
    """
    get_langfuse().flush()


def get_langchain_handler():
    """A LangChain callback that records model calls (tokens, cost) in Langfuse.

    Used by F4. Imported lazily so this module works without LangChain installed.
    """
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()
