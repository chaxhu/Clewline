"""Shared pytest setup.

Two kinds of test run:
  uv run pytest            unit tests only. No network, and tracing is OFF so nothing is sent.
  uv run pytest -m live    real model calls. Tracing stays ON, because every model call
                           must be traced (governance rule 2).
  uv run pytest -m eval    evaluation runs (F5). Tracing stays ON.

pytest_configure runs before any test module is imported, so it runs before the
Langfuse client is created. load_dotenv() never overrides a value that is already
set, so the switches below win over .env.

Evaluation runs also turn the OpenAI -> Gemini fallback OFF, so every score
comes from one model and a failed call is counted as an error. They tag their
traces and reports with environment "eval", so they never mix with "dev" traces.
"""

import os


def pytest_configure(config):
    markexpr = (config.option.markexpr or "").strip()
    selects_real_runs = not markexpr.startswith("not") and ("live" in markexpr or "eval" in markexpr)
    if not selects_real_runs:
        os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
    if selects_real_runs and "eval" in markexpr:
        os.environ.setdefault("MODEL_FALLBACK", "off")  # a value set in the shell still wins
        os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", "eval")
