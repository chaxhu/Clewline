"""Shared pytest setup.

pytest runs this file before any test module is imported.
Unit tests must never send traces, so tracing is switched off here.
load_dotenv() does not override values that are already set, so this wins over .env.
"""

import os

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
