"""Run one step against the council complaints test set and write a dated report.

    uv run python scripts/run_eval.py keyword_urgency
    uv run python scripts/run_eval.py keyword_urgency --cases case_001,case_003
    uv run python scripts/run_eval.py keyword_urgency --limit 5
    uv run python scripts/run_eval.py keyword_urgency --resume      # after a stop
    uv run python scripts/run_eval.py keyword_urgency --fresh       # start again
    uv run python scripts/run_eval.py keyword_urgency --max-cost 0.25

The model fallback is always off here, so every score comes from one model.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so `core` imports when run as a script

from core.evaluation import DatasetError, RunInProgress, run_evaluation  # noqa: E402
from packs.council_complaints import DATA_DIR  # noqa: E402
from packs.council_complaints.baselines import STEPS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=sorted(STEPS))
    parser.add_argument("--cases", help="comma-separated case ids, e.g. case_001,case_003")
    parser.add_argument("--limit", type=int, help="run only the first N (selected) cases")
    parser.add_argument("--resume", action="store_true", help="continue an unfinished run")
    parser.add_argument("--fresh", action="store_true", help="start again, discarding an unfinished run")
    parser.add_argument("--max-cost", type=float, help="spend cap in USD (default MAX_RUN_COST_USD, then 0.50)")
    args = parser.parse_args()

    try:
        report = run_evaluation(
            STEPS[args.step], args.step, DATA_DIR,
            case_ids=args.cases.split(",") if args.cases else None,
            limit=args.limit, resume=args.resume, fresh=args.fresh, max_cost_usd=args.max_cost,
        )
    except (RunInProgress, DatasetError) as error:
        print(error, file=sys.stderr)
        return 2

    h = report["header"]
    print(f"{h['step']}: {h['status']}. Answered {h['answered']} of {h['cases_selected']}, "
          f"errors {h['errors']}, not run {h['not_run']}, spent ${h['spent_usd']:.4f}.")
    if h["status"] == "stopped":
        print(f"Stopped: {h['stop_reason']}\nRun again with --resume to continue.")
    print(f"Report: {report['paths']['markdown']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
