"""Shared pytest setup.

Two kinds of test run:
  uv run pytest            unit tests only. No network, and tracing is OFF so nothing is sent.
  uv run pytest -m live    real model calls. Tracing stays ON, because every model call
                           must be traced (governance rule 2).
  uv run pytest -m eval    evaluation runs (F5). Tracing stays ON.

pytest_configure runs before any test module is imported, so it runs before the
Langfuse client is created. load_dotenv() never overrides a value that is already
set, so the switch below wins over .env.
"""

import os


def pytest_configure(config):
    markexpr = (config.option.markexpr or "").strip()
    selects_real_runs = not markexpr.startswith("not") and ("live" in markexpr or "eval" in markexpr)
    if not selects_real_runs:
        os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
