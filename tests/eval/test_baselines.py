"""F5 evaluation run: score the naive rule baselines on the full test set.

Skipped in normal runs. Run with:   uv run pytest -m eval
Writes reports/YYYY-MM-DD_keyword_urgency.md and reports/YYYY-MM-DD_all_verified.md
(plus .json). These are the scores every AI step has to beat.
"""

import pytest

from core.evaluation import run_evaluation
from packs.council_complaints import DATA_DIR
from packs.council_complaints.baselines import STEPS

pytestmark = pytest.mark.eval


@pytest.mark.parametrize("step_name", sorted(STEPS))
def test_baseline_full_run(step_name):
    report = run_evaluation(STEPS[step_name], step_name, DATA_DIR, fresh=True)
    h = report["header"]
    print(f"\n{step_name}: {report['paths']['markdown']}")
    assert h["status"] == "complete"
    assert h["answered"] == h["cases_in_test_set"] == 20
    assert h["errors"] == 0
    assert h["models_used"] is None  # rule baselines make no model calls
