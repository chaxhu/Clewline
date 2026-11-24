"""Send one test trace to local Langfuse, with one nested span.

What you will see in the UI (Tracing > Traces):

    test_trace_pipeline          <- the TRACE: one whole run, top level
      └─ count_words             <- a SPAN: one step inside that run

No model is called. The text is a synthetic complaint from the test set.

Run:  uv run python scripts/send_test_trace.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schema import Case  # noqa: E402
from core.tracing import check_connection, flush, get_langfuse, observe, tracing_configured  # noqa: E402

CASE_FILE = Path(__file__).resolve().parent.parent / "data" / "council_complaints" / "cases" / "case_005.json"


@observe(name="count_words")
def count_words(text: str) -> int:
    """The nested call. Because it is decorated too, it becomes a child span."""
    return len(text.split())


@observe(name="test_trace_pipeline")
def pipeline(case: Case) -> dict:
    """The outer call. It is the first decorated function to run, so it becomes the trace."""
    words = count_words(case.source_text)
    trace_id = get_langfuse().get_current_trace_id()
    return {"case_id": case.id, "word_count": words, "trace_id": trace_id}


def main() -> None:
    if not tracing_configured():
        sys.exit("Langfuse keys are missing from .env. See README > Tracing setup.")
    if not check_connection():
        sys.exit("Could not authenticate with Langfuse. Is `docker compose up -d` running, and are the keys right?")

    case = Case.model_validate_json(CASE_FILE.read_text(encoding="utf-8"))
    result = pipeline(case)
    flush()  # make sure the trace is sent before the script exits

    print(f"Sent trace for {result['case_id']} ({result['word_count']} words)")
    print(f"Open it here: {get_langfuse().get_trace_url(trace_id=result['trace_id'])}")


if __name__ == "__main__":
    main()
