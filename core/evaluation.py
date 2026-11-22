"""F5. Evaluation runner: score any step against the labelled test set.

A "step" is any function that takes a Case and returns a StepOutput. The
runner gives each step only the Case. It joins the answers (CaseLabel) back
in afterwards, by case_id, to score the output. So no step can see the answers.

    from core.evaluation import run_evaluation
    report = run_evaluation(my_step, "my_step", "data/council_complaints")

What a run guarantees:
  - The model fallback is OFF, so every score comes from one model.
  - A step that raises (for example a call that failed after all retries) is
    counted as an ERROR, never as a wrong answer. Scores use answered cases only.
  - Progress is saved after every case. A run stopped by the spend cap (or a
    crash) continues with resume=True, skipping cases already answered.
  - A subset can be run with case_ids=[...] or limit=N.
  - The report (reports/YYYY-MM-DD_<step>.md and .json) starts with a header:
    status, code version, test set fingerprint, models used, fallback, spend,
    and when the run started and was resumed.

Nothing here is specific to council complaints (governance rule 7).
"""

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core import models
from core.schema import Case, CaseLabel, Citation, Issue, Span, StrictModel, TriageResult
from core.tracing import REPO_ROOT, flush, git_release, observe, tracing_configured

REPORTS_DIR = Path("reports")
STATE_DIR = Path(".cache/eval_runs")   # progress files, gitignored


class StepOutput(StrictModel):
    """What a step returns. Each part is optional; only the parts present are scored."""

    issues: list[Issue] | None = None
    triage: TriageResult | None = None
    citations: list[Citation] | None = None


Step = Callable[[Case], StepOutput]


class DatasetError(ValueError):
    """The test set is inconsistent, or a requested case does not exist."""


class RunInProgress(RuntimeError):
    """An unfinished run exists and neither resume nor fresh was chosen."""


# ---- Loading the test set ---------------------------------------------------------

@dataclass(frozen=True)
class LabelledCase:
    case: Case
    label: CaseLabel


def load_dataset(data_dir: str | Path) -> list[LabelledCase]:
    """Read cases/ and labels/ and join them by case id, sorted by id."""
    data_dir = Path(data_dir)
    cases = {}
    for path in sorted((data_dir / "cases").glob("*.json")):
        case = Case.model_validate_json(path.read_text(encoding="utf-8"))
        cases[case.id] = case
    labels = {}
    for path in sorted((data_dir / "labels").glob("*.json")):
        label = CaseLabel.model_validate_json(path.read_text(encoding="utf-8"))
        labels[label.case_id] = label
    if not cases:
        raise DatasetError(f"No cases found in {data_dir / 'cases'}")
    if set(cases) != set(labels):
        raise DatasetError(
            f"Cases and labels do not match. No label: {sorted(set(cases) - set(labels))}. "
            f"No case: {sorted(set(labels) - set(cases))}."
        )
    return [LabelledCase(cases[i], labels[i]) for i in sorted(cases)]


def dataset_fingerprint(data_dir: str | Path) -> str:
    """A short hash of every case and label file. If a label changes, so does this,
    so two reports are only comparable when their fingerprints match."""
    data_dir = Path(data_dir)
    digest = hashlib.sha256()
    for path in sorted([*data_dir.glob("cases/*.json"), *data_dir.glob("labels/*.json")]):
        digest.update(path.relative_to(data_dir).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))  # same hash on Windows and Linux
    return digest.hexdigest()[:12]


def select_cases(dataset: list[LabelledCase], case_ids: list[str] | None = None, limit: int | None = None) -> list[LabelledCase]:
    """The cases to run: all of them, the named ones, and/or the first `limit`."""
    selected = dataset
    if case_ids:
        known = {lc.case.id for lc in dataset}
        unknown = [c for c in case_ids if c not in known]
        if unknown:
            raise DatasetError(f"Unknown case id(s): {unknown}")
        wanted = set(case_ids)
        selected = [lc for lc in dataset if lc.case.id in wanted]
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise DatasetError("No cases selected.")
    return selected


# ---- Scoring one case -----------------------------------------------------------------

def overlap(a: Span | None, b: Span | None) -> int:
    """How many characters two spans share. 0 if either is missing (ungrounded)."""
    if a is None or b is None:
        return 0
    return max(0, min(a.end, b.end) - max(a.start, b.start))


def match_by_span(predicted: list, gold: list, same: Callable = lambda p, g: True) -> list[tuple[int, int]]:
    """Pair predicted items with gold items one to one, by overlapping spans.

    Biggest overlap is paired first, and each item is used at most once.
    `same` adds a condition, for example "same category". An ungrounded item
    (no span) can never be matched, so it counts as unmatched.
    Returns (predicted index, gold index) pairs.
    """
    candidates = sorted(
        ((overlap(p.span, g.span), i, j)
         for i, p in enumerate(predicted) for j, g in enumerate(gold)
         if overlap(p.span, g.span) > 0 and same(p, g)),
        key=lambda c: (-c[0], c[1], c[2]),
    )
    used_p, used_g, pairs = set(), set(), []
    for _, i, j in candidates:
        if i not in used_p and j not in used_g:
            pairs.append((i, j))
            used_p.add(i)
            used_g.add(j)
    return sorted(pairs)


STATUSES = ("verified", "not_found", "needs_review")


def score_case(output: StepOutput, label: CaseLabel) -> dict:
    """Raw counts for one case. Rates are worked out later, over all cases."""
    scores: dict = {}
    if output.triage is not None:
        predicted, gold = output.triage.urgency_band, label.urgency_band
        scores["urgency"] = {
            "gold": gold, "predicted": predicted, "contested": label.contested,
            "exact": predicted == gold, "within_one": abs(predicted - gold) <= 1,
        }
    if output.citations is not None:
        pairs = match_by_span(output.citations, label.citations)
        per_status = {s: {"gold": 0, "correct": 0} for s in STATUSES}
        for g in label.citations:
            per_status[g.status]["gold"] += 1
        correct = 0
        for i, j in pairs:
            if output.citations[i].status == label.citations[j].status:
                correct += 1
                per_status[label.citations[j].status]["correct"] += 1
        scores["citations"] = {
            "gold": len(label.citations), "predicted": len(output.citations), "found": len(pairs),
            "status_correct": correct, "extra": len(output.citations) - len(pairs), "per_status": per_status,
        }
    if output.issues is not None:
        pairs = match_by_span(output.issues, label.issues, same=lambda p, g: p.category == g.category)
        scores["issues"] = {"gold": len(label.issues), "predicted": len(output.issues), "matched": len(pairs)}
    items = (output.issues or []) + (output.citations or [])
    scores["grounding"] = {"items": len(items), "grounded": sum(x.is_grounded for x in items)}
    return scores


# ---- Summing up a run -----------------------------------------------------------------

def rate(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole


def summarise(rows: list[dict]) -> dict:
    """Turn per-case counts into rates. Only answered ("ok") cases are scored."""
    ok = [r["scores"] for r in rows if r["status"] == "ok"]
    summary: dict = {}

    urgency = [s["urgency"] for s in ok if "urgency" in s]
    if urgency:
        def block(items):
            return {"n": len(items),
                    "exact": rate(sum(u["exact"] for u in items), len(items)),
                    "within_one": rate(sum(u["within_one"] for u in items), len(items))}
        summary["urgency"] = {
            "all": block(urgency),
            "not_contested": block([u for u in urgency if not u["contested"]]),
            "contested": block([u for u in urgency if u["contested"]]),
        }

    citations = [s["citations"] for s in ok if "citations" in s]
    if citations:
        gold = sum(c["gold"] for c in citations)
        found = sum(c["found"] for c in citations)
        correct = sum(c["status_correct"] for c in citations)
        per_status = {}
        for status in STATUSES:
            g = sum(c["per_status"][status]["gold"] for c in citations)
            k = sum(c["per_status"][status]["correct"] for c in citations)
            per_status[status] = {"gold": g, "correct": k, "recall": rate(k, g)}
        summary["citations"] = {
            "gold": gold, "found": found, "status_correct": correct,
            "extra": sum(c["extra"] for c in citations),
            "found_rate": rate(found, gold),
            "status_accuracy": rate(correct, gold),          # missed citations count as wrong
            "status_accuracy_on_found": rate(correct, found),
            "per_status": per_status,
        }

    issues = [s["issues"] for s in ok if "issues" in s]
    if issues:
        matched = sum(i["matched"] for i in issues)
        predicted = sum(i["predicted"] for i in issues)
        gold = sum(i["gold"] for i in issues)
        precision, recall = rate(matched, predicted), rate(matched, gold)
        f1 = None if not precision or not recall else 2 * precision * recall / (precision + recall)
        summary["issues"] = {"gold": gold, "predicted": predicted, "matched": matched,
                             "precision": precision, "recall": recall, "f1": f1}

    items = sum(s["grounding"]["items"] for s in ok)
    grounded = sum(s["grounding"]["grounded"] for s in ok)
    if items:
        summary["grounding"] = {"items": items, "grounded": grounded, "rate": rate(grounded, items)}
    return summary


# ---- Running ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _display_path(path: str | Path) -> str:
    """The path relative to the repo, so reports never show where your machine keeps it."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.name


@contextmanager
def fallback_off():
    """Switch the model fallback off for the duration of a run, then restore it."""
    before = os.environ.get("MODEL_FALLBACK")
    os.environ["MODEL_FALLBACK"] = "off"
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("MODEL_FALLBACK", None)
        else:
            os.environ["MODEL_FALLBACK"] = before


def _merge_calls(a: dict, b: dict) -> dict:
    """Add two model-call summaries together (one from each session of a run)."""
    out = {k: dict(v) for k, v in a.items()}
    for key, row in b.items():
        if key not in out:
            out[key] = dict(row)
        else:
            for field_name, value in row.items():
                out[key][field_name] += value
    return out


def _save(path: Path, state: dict) -> None:
    """Write progress safely: to a temp file first, then swap it in.
    A crash mid-write can never leave a half-written progress file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


@observe(name="eval_case")
def _run_case(step: Step, case: Case) -> StepOutput:
    output = step(case)
    if not isinstance(output, StepOutput):
        raise TypeError(f"A step must return StepOutput, got {type(output).__name__}")
    return output


@observe(name="evaluation_run")
def run_evaluation(
    step: Step,
    step_name: str,
    data_dir: str | Path,
    *,
    case_ids: list[str] | None = None,
    limit: int | None = None,
    resume: bool = False,
    fresh: bool = False,
    max_cost_usd: float | None = None,
    reports_dir: str | Path = REPORTS_DIR,
    state_dir: str | Path = STATE_DIR,
    now: Callable[[], datetime] = _utcnow,
) -> dict:
    """Run `step` on the selected cases, score it, and write the dated report.

    resume        continue an unfinished run: skip answered cases, retry errors.
    fresh         start again even if an unfinished run exists.
    max_cost_usd  spend cap for the whole run. Default: MAX_RUN_COST_USD, then $0.50.
    Returns the report as a dict, with "paths" naming the files written.
    """
    dataset = load_dataset(data_dir)
    selected = select_cases(dataset, case_ids, limit)
    selection = [lc.case.id for lc in selected]
    is_subset = len(selection) < len(dataset)
    key = step_name + (f"_subset-{hashlib.sha256(','.join(selection).encode()).hexdigest()[:8]}" if is_subset else "")
    state_path = Path(state_dir) / f"{key}.json"
    fingerprint = dataset_fingerprint(data_dir)

    existing = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
    if resume:
        if existing is None:
            raise RunInProgress(f"There is no saved run of '{step_name}' for these cases to resume.")
        if existing["fingerprint"] != fingerprint:
            raise DatasetError("The test set has changed since this run started, so it cannot be resumed. Use fresh.")
        if all(existing["rows"].get(c, {}).get("status") == "ok" for c in selection):
            raise RunInProgress(f"The run of '{step_name}' already answered every case. Nothing to resume.")
        state = existing
    else:
        if existing and existing["status"] != "complete" and not fresh:
            done = sum(1 for r in existing["rows"].values() if r["status"] == "ok")
            raise RunInProgress(
                f"An unfinished run of '{step_name}' exists ({done} of {len(existing['selection'])} cases answered). "
                "Use resume to continue it, or fresh to start again."
            )
        state = {
            "step": step_name, "key": key, "data_dir": _display_path(data_dir), "fingerprint": fingerprint,
            "dataset_size": len(dataset), "selection": selection, "is_subset": is_subset,
            "max_cost_usd": None, "spent_usd": 0.0, "model_calls": {}, "rows": {},
            "sessions": [], "status": "running",
        }

    budget = models.start_run(max_cost_usd, already_spent_usd=state["spent_usd"])
    state["max_cost_usd"] = budget.max_cost_usd
    calls_before = state["model_calls"]
    session = {"started_at": now().isoformat(timespec="seconds"), "resumed": resume, "ended_at": None, "outcome": None}
    state["sessions"].append(session)
    state["status"] = "running"
    _save(state_path, state)

    stop_reason = None
    with fallback_off():
        for lc in selected:
            case_id = lc.case.id
            if state["rows"].get(case_id, {}).get("status") == "ok":
                continue  # answered in an earlier session
            try:
                output = _run_case(step, lc.case)
                row = {"case_id": case_id, "status": "ok", "scores": score_case(output, lc.label)}
            except models.SpendCapReached as error:
                stop_reason = str(error)  # stop cleanly; this case is not counted at all
                break
            except Exception as error:  # the step failed: an error, not a wrong answer
                row = {"case_id": case_id, "status": "error", "error": {
                    "type": type(error).__name__,
                    "message": str(error)[:500],
                    "call_failure": isinstance(error, models.CALL_FAILURES),
                }}
            row["finished_at"] = now().isoformat(timespec="seconds")
            state["rows"][case_id] = row
            state["spent_usd"] = budget.spent_usd
            state["model_calls"] = _merge_calls(calls_before, budget.summary())
            _save(state_path, state)

    state["spent_usd"] = budget.spent_usd
    state["model_calls"] = _merge_calls(calls_before, budget.summary())
    state["status"] = "stopped" if stop_reason else "complete"
    session["ended_at"] = now().isoformat(timespec="seconds")
    session["outcome"] = f"stopped: {stop_reason}" if stop_reason else "complete"
    _save(state_path, state)

    report = build_report(state, now())
    report["paths"] = write_report(report, reports_dir, now())
    if tracing_configured():
        flush()
    return report


# ---- Reports ---------------------------------------------------------------------------

def build_report(state: dict, written_at: datetime) -> dict:
    rows = [state["rows"][c] for c in state["selection"] if c in state["rows"]]
    answered = sum(r["status"] == "ok" for r in rows)
    errors = [r for r in rows if r["status"] == "error"]
    resumed_at = [s["started_at"] for s in state["sessions"] if s["resumed"]]
    header = {
        "step": state["step"],
        "status": state["status"],
        "stop_reason": next((s["outcome"][9:] for s in reversed(state["sessions"]) if (s["outcome"] or "").startswith("stopped")), None)
        if state["status"] == "stopped" else None,
        "written_at": written_at.isoformat(timespec="seconds"),
        "code_version": git_release() or "unknown",
        "test_set": state["data_dir"],
        "test_set_fingerprint": state["fingerprint"],
        "cases_in_test_set": state["dataset_size"],
        "cases_selected": len(state["selection"]),
        "subset": state["selection"] if state["is_subset"] else None,
        "answered": answered,
        "errors": len(errors),
        "not_run": len(state["selection"]) - len(rows),
        "models_used": sorted(state["model_calls"]) or None,
        "fallback": "off",
        "spent_usd": round(state["spent_usd"], 6),
        "max_cost_usd": state["max_cost_usd"],
        "started_at": state["sessions"][0]["started_at"],
        "resumed": bool(resumed_at),
        "resumed_at": resumed_at,
    }
    return {
        "header": header,
        "summary": summarise(rows),
        "errors": [{"case_id": r["case_id"], **r["error"]} for r in errors],
        "model_calls": state["model_calls"],
        "rows": rows,
    }


def report_paths(step: str, is_subset: bool, reports_dir: str | Path, day: datetime) -> tuple[Path, Path]:
    stem = f"{day.date().isoformat()}_{step}{'_subset' if is_subset else ''}"
    return Path(reports_dir) / f"{stem}.md", Path(reports_dir) / f"{stem}.json"


def write_report(report: dict, reports_dir: str | Path, day: datetime) -> dict:
    md_path, json_path = report_paths(report["header"]["step"], bool(report["header"]["subset"]), reports_dir, day)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps({k: v for k, v in report.items() if k != "paths"}, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"markdown": md_path.as_posix(), "json": json_path.as_posix()}


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render_markdown(report: dict) -> str:
    h, s = report["header"], report["summary"]
    status = "Complete" if h["status"] == "complete" else f"Stopped: {h['stop_reason']}"
    cases = f"{h['cases_selected']} of {h['cases_in_test_set']}"
    if h["subset"]:
        cases += f" (subset: {', '.join(h['subset'])})"
    resumed = "No" if not h["resumed"] else "Yes, at " + ", ".join(h["resumed_at"])
    lines = [
        f"# Evaluation: {h['step']}",
        "",
        "| | |",
        "| --- | --- |",
        f"| Status | {status} |",
        f"| Written | {h['written_at']} |",
        f"| Code version | `{h['code_version']}` |",
        f"| Test set | `{h['test_set']}` (fingerprint `{h['test_set_fingerprint']}`) |",
        f"| Cases | {cases} |",
        f"| Answered | {h['answered']} |",
        f"| Errors | {h['errors']} (not counted as wrong answers) |",
        f"| Not run | {h['not_run']} |",
        f"| Models used | {', '.join(h['models_used']) if h['models_used'] else 'none (no model calls)'} |",
        f"| Fallback | {h['fallback']} (every score comes from one model) |",
        f"| Spend | ${h['spent_usd']:.4f} of ${h['max_cost_usd']:.2f} cap |",
        f"| Started | {h['started_at']} |",
        f"| Resumed | {resumed} |",
        "",
        "## Results",
        "",
        f"Scores use the {h['answered']} answered cases only. Errors are listed separately below.",
        "",
    ]
    if "urgency" in s:
        u = s["urgency"]
        lines += ["### Urgency band", "", "| Cases | n | Exact | Within one band |", "| --- | --- | --- | --- |"]
        for name, label in (("all", "All"), ("not_contested", "Not contested"), ("contested", "Contested")):
            lines.append(f"| {label} | {u[name]['n']} | {_pct(u[name]['exact'])} | {_pct(u[name]['within_one'])} |")
        lines.append("")
    if "citations" in s:
        c = s["citations"]
        lines += [
            "### Citations", "",
            f"- Found {c['found']} of {c['gold']} labelled citations ({_pct(c['found_rate'])}), plus {c['extra']} extra.",
            f"- Status right for {c['status_correct']} of {c['gold']} ({_pct(c['status_accuracy'])}). "
            f"On the found ones only: {_pct(c['status_accuracy_on_found'])}.",
            "", "| Labelled status | Labelled | Got right | Recall |", "| --- | --- | --- | --- |",
        ]
        for status, row in c["per_status"].items():
            lines.append(f"| {status} | {row['gold']} | {row['correct']} | {_pct(row['recall'])} |")
        lines.append("")
    if "issues" in s:
        i = s["issues"]
        lines += [
            "### Issues", "",
            f"- Matched {i['matched']} of {i['gold']} labelled issues (same category, overlapping text), "
            f"from {i['predicted']} predicted.",
            f"- Precision {_pct(i['precision'])}, recall {_pct(i['recall'])}, F1 {_pct(i['f1'])}.", "",
        ]
    if "grounding" in s:
        g = s["grounding"]
        lines += ["### Grounding", "",
                  f"{g['grounded']} of {g['items']} predicted items link to the source text ({_pct(g['rate'])}).", ""]
    if not s:
        lines += ["No cases were answered, so there is nothing to score.", ""]

    lines += ["## Errors", ""]
    if report["errors"]:
        lines += ["| Case | Error | Call failure | Message |", "| --- | --- | --- | --- |"]
        for e in report["errors"]:
            message = e["message"].replace("|", "/").replace("\n", " ")[:160]
            lines.append(f"| {e['case_id']} | {e['type']} | {'yes' if e['call_failure'] else 'no'} | {message} |")
    else:
        lines.append("None.")
    lines += ["", "## Model calls", ""]
    if report["model_calls"]:
        lines += ["| Model | Calls | Retries | Failed after retries | Wait (s) | Tokens in / out | Cost |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for name, m in sorted(report["model_calls"].items()):
            lines.append(f"| {name} | {m['calls']} | {m['retries']} | {m['failed_after_retries']} | "
                         f"{m['wait_s']:.1f} | {m['input_tokens']} / {m['output_tokens']} | ${m['cost_usd']:.4f} |")
    else:
        lines.append("None. This step makes no model calls.")

    lines += ["", "## Per case", "", "| Case | Result | Band (label / predicted) | Citations right | Issues matched |",
              "| --- | --- | --- | --- | --- |"]
    for r in report["rows"]:
        if r["status"] != "ok":
            lines.append(f"| {r['case_id']} | error | | | |")
            continue
        sc = r["scores"]
        band = f"{sc['urgency']['gold']} / {sc['urgency']['predicted']}" if "urgency" in sc else ""
        if "urgency" in sc and sc["urgency"]["contested"]:
            band += " (contested)"
        cit = f"{sc['citations']['status_correct']} of {sc['citations']['gold']}" if "citations" in sc else ""
        iss = f"{sc['issues']['matched']} of {sc['issues']['gold']}" if "issues" in sc else ""
        lines.append(f"| {r['case_id']} | ok | {band} | {cit} | {iss} |")
    return "\n".join(lines) + "\n"
