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

Every trace is also tagged with where it came from:
    service name  "clewline"           (OTEL_SERVICE_NAME)
    environment   "dev"                (LANGFUSE_TRACING_ENVIRONMENT)
    release       current git commit   (LANGFUSE_RELEASE), e.g. "dc5cec8" or "dc5cec8-dirty"
Each is only a default: a value already set in .env or the shell wins.
"""

import os
import subprocess
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv

# Load .env into os.environ before Langfuse reads its settings.
# Values that are already set (for example by tests) win over .env.
load_dotenv()

SERVICE_NAME = "clewline"
DEFAULT_ENVIRONMENT = "dev"
REPO_ROOT = Path(__file__).resolve().parent.parent


def git_release() -> str | None:
    """Short hash of the current git commit, plus "-dirty" if there are uncommitted changes.

    "-dirty" matters for governance: it tells you the trace came from code
    that does not exactly match any commit.
    """

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=5
        ).stdout.strip()

    try:
        commit = git("rev-parse", "--short", "HEAD")
        dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        return None  # git not installed, or not a git repository
    return f"{commit}-dirty" if dirty else commit


# These must be set before the Langfuse client is created, because it reads
# them once when it starts. setdefault() keeps any value you set yourself.
os.environ.setdefault("OTEL_SERVICE_NAME", SERVICE_NAME)
os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", DEFAULT_ENVIRONMENT)
_release = git_release()
if _release:
    os.environ.setdefault("LANGFUSE_RELEASE", _release)

from langfuse import get_client, observe  # noqa: E402

__all__ = [
    "observe",
    "get_langfuse",
    "flush",
    "tracing_configured",
    "check_connection",
    "get_langchain_handler",
    "git_release",
]

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
    """Ask the Langfuse server whether our keys are valid. Makes one network call.

    On failure, the real underlying error is printed to stderr, for example
    a refused connection or a 401 Unauthorized. Key values are never printed.
    """
    if not tracing_configured():
        missing = [n for n in REQUIRED_VARS if not os.getenv(n)]
        print(f"Langfuse check failed: missing {', '.join(missing)} in .env", file=sys.stderr)
        return False
    base_url = os.getenv("LANGFUSE_BASE_URL")
    try:
        ok = get_langfuse().auth_check()
    except Exception as error:  # show the real cause instead of hiding it
        print(f"Langfuse check failed at {base_url}: {type(error).__name__}: {error}", file=sys.stderr)
        return False
    if not ok:
        print(f"Langfuse check failed at {base_url}: server rejected the keys", file=sys.stderr)
    return ok


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
