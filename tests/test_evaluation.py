"""Tests for core/evaluation.py, on a tiny test set built in a temp folder."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from langchain_core.exceptions import ModelRateLimitError

from core import evaluation, models
from core.evaluation import (
    DatasetError,
    RunInProgress,
    StepOutput,
    load_dataset,
    match_by_span,
    run_evaluation,
    score_case,
    select_cases,
    summarise,
)
from core.schema import Case, CaseLabel, Citation, Issue, RiskFlag, Span, TriageResult

TEXT = "The ceiling fell in. Housing Act 1985 applies. Also the bins were missed."
#       0         1         2         3         4         5         6         7
#       0123456789012345678901234567890123456789012345678901234567890123456789012


def span_of(text: str, quote: str) -> Span:
    start = text.index(quote)
    return Span(start=start, end=start + len(quote))


def make_label(case_id: str, band: int = 4, contested: bool = False) -> CaseLabel:
    return CaseLabel(
        case_id=case_id,
        urgency_band=band,
        contested=contested,
        issues=[
            Issue(summary="Ceiling collapse", category="housing_repairs", span=span_of(TEXT, "The ceiling fell in.")),
            Issue(summary="Missed bins", category="waste_recycling", span=span_of(TEXT, "the bins were missed")),
        ],
        citations=[Citation(raw_text="Housing Act 1985", status="verified", span=span_of(TEXT, "Housing Act 1985"))],
    )


@pytest.fixture
def dataset(tmp_path):
    """Three cases: bands 4, 2 and 3 (case_c contested)."""
    data = tmp_path / "data"
    (data / "cases").mkdir(parents=True)
    (data / "labels").mkdir()
    for case_id, band, contested in (("case_a", 4, False), ("case_b", 2, False), ("case_c", 3, True)):
        case = Case(id=case_id, source_text=TEXT, received_date="2026-11-01", channel="email")
        (data / "cases" / f"{case_id}.json").write_text(case.model_dump_json(), encoding="utf-8")
        (data / "labels" / f"{case_id}.json").write_text(make_label(case_id, band, contested).model_dump_json(), encoding="utf-8")
    return data


@pytest.fixture
def dirs(tmp_path):
    return {"reports_dir": tmp_path / "reports", "state_dir": tmp_path / "state"}


@pytest.fixture(autouse=True)
def no_tracing(monkeypatch):
    monkeypatch.setattr(evaluation, "tracing_configured", lambda: False)
    monkeypatch.delenv("MAX_RUN_COST_USD", raising=False)


class Clock:
    """A fake clock: each call returns a time one minute later."""

    def __init__(self, start=datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)):
        self.t = start

    def __call__(self):
        self.t += timedelta(minutes=1)
        return self.t


def band_step(band: int):
    def step(case):
        return StepOutput(triage=TriageResult(urgency_band=band, reasons=["test"]))
    return step


# ---- Loading and selecting ------------------------------------------------------------

def test_load_dataset_joins_cases_and_labels(dataset):
    loaded = load_dataset(dataset)
    assert [lc.case.id for lc in loaded] == ["case_a", "case_b", "case_c"]
    assert all(lc.case.id == lc.label.case_id for lc in loaded)


def test_load_dataset_rejects_a_case_without_a_label(dataset):
    (dataset / "labels" / "case_b.json").unlink()
    with pytest.raises(DatasetError, match=r"No label: \['case_b'\]"):
        load_dataset(dataset)


def test_real_test_set_loads():
    from packs.council_complaints import DATA_DIR
    assert len(load_dataset(DATA_DIR)) == 20


def test_select_by_ids_and_limit(dataset):
    loaded = load_dataset(dataset)
    assert [lc.case.id for lc in select_cases(loaded, ["case_c", "case_a"])] == ["case_a", "case_c"]
    assert [lc.case.id for lc in select_cases(loaded, limit=2)] == ["case_a", "case_b"]
    with pytest.raises(DatasetError, match="Unknown case id"):
        select_cases(loaded, ["case_z"])


def test_fingerprint_changes_when_a_label_changes(dataset):
    before = evaluation.dataset_fingerprint(dataset)
    (dataset / "labels" / "case_a.json").write_text(make_label("case_a", band=5).model_dump_json(), encoding="utf-8")
    assert evaluation.dataset_fingerprint(dataset) != before


# ---- Matching and scoring ---------------------------------------------------------------

def test_match_by_span_is_one_to_one_and_prefers_bigger_overlap():
    gold = [Citation(raw_text="g", status="verified", span=Span(start=0, end=10))]
    predicted = [
        Citation(raw_text="small", status="verified", span=Span(start=8, end=12)),   # overlaps 2
        Citation(raw_text="big", status="verified", span=Span(start=0, end=9)),      # overlaps 9
        Citation(raw_text="ungrounded", status="verified"),
    ]
    assert match_by_span(predicted, gold) == [(1, 0)]


def test_citation_scores():
    label = make_label("x")
    label.citations.append(Citation(raw_text="Fake Act 2021", status="not_found", span=Span(start=60, end=70)))
    output = StepOutput(citations=[
        Citation(raw_text="Housing Act 1985", status="verified", span=span_of(TEXT, "Housing Act 1985")),  # right
        Citation(raw_text="Fake", status="verified", span=Span(start=62, end=68)),                          # found, wrong status
        Citation(raw_text="nowhere", status="verified", span=Span(start=0, end=3)),                         # extra
    ])
    c = score_case(output, label)["citations"]
    assert (c["gold"], c["found"], c["status_correct"], c["extra"]) == (2, 2, 1, 1)
    assert c["per_status"]["not_found"] == {"gold": 1, "correct": 0}


def test_issue_scores_need_same_category_and_overlap():
    output = StepOutput(issues=[
        Issue(summary="ceiling", category="housing_repairs", span=span_of(TEXT, "ceiling fell")),   # match
        Issue(summary="bins", category="highways", span=span_of(TEXT, "bins were missed")),       # wrong category
        Issue(summary="ungrounded", category="waste_recycling"),                                    # no span
    ])
    i = score_case(output, make_label("x"))["issues"]
    assert (i["gold"], i["predicted"], i["matched"]) == (2, 3, 1)
    s = summarise([{"status": "ok", "scores": score_case(output, make_label("x"))}])
    assert s["issues"]["precision"] == pytest.approx(1 / 3)
    assert s["issues"]["recall"] == pytest.approx(1 / 2)
    assert s["issues"]["f1"] == pytest.approx(0.4)
    assert s["grounding"] == {"items": 3, "grounded": 2, "rate": pytest.approx(2 / 3)}


def test_urgency_exact_within_one_and_contested_split():
    rows = [
        {"status": "ok", "scores": score_case(band_step(4)(None), make_label("a", 4))},                  # exact
        {"status": "ok", "scores": score_case(band_step(3)(None), make_label("b", 4))},                  # within one
        {"status": "ok", "scores": score_case(band_step(1)(None), make_label("c", 4, contested=True))},  # far off
    ]
    u = summarise(rows)["urgency"]
    assert u["all"] == {"n": 3, "exact": pytest.approx(1 / 3), "within_one": pytest.approx(2 / 3)}
    assert u["not_contested"] == {"n": 2, "exact": 0.5, "within_one": 1.0}
    assert u["contested"] == {"n": 1, "exact": 0.0, "within_one": 0.0}


def test_only_parts_the_step_returns_are_scored():
    scores = score_case(band_step(4)(None), make_label("a"))
    assert "urgency" in scores and "citations" not in scores and "issues" not in scores


def test_errors_are_left_out_of_the_scores():
    rows = [
        {"status": "ok", "scores": score_case(band_step(4)(None), make_label("a", 4))},
        {"status": "error", "error": {"type": "RetriesExhausted"}},
    ]
    assert summarise(rows)["urgency"]["all"]["n"] == 1


# ---- Running ---------------------------------------------------------------------------

def test_full_run_writes_dated_reports(dataset, dirs):
    report = run_evaluation(band_step(3), "fixed_band", dataset, now=Clock(), **dirs)
    h = report["header"]
    assert h["status"] == "complete" and h["answered"] == 3 and h["errors"] == 0
    assert h["subset"] is None and h["fallback"] == "off" and h["resumed"] is False
    assert h["models_used"] is None
    assert report["paths"]["markdown"].endswith("reports/2026-11-22_fixed_band.md")
    md = (dirs["reports_dir"] / "2026-11-22_fixed_band.md").read_text(encoding="utf-8")
    assert "| Status | Complete |" in md and "fingerprint" in md and "none (no model calls)" in md
    saved = json.loads((dirs["reports_dir"] / "2026-11-22_fixed_band.json").read_text(encoding="utf-8"))
    assert saved["summary"]["urgency"]["all"]["n"] == 3


def test_step_errors_are_counted_separately(dataset, dirs):
    def flaky(case):
        if case.id == "case_b":
            raise models.RetriesExhausted("openai", "gpt-6-luna", 4, "rate_limit", "429")
        if case.id == "case_c":
            raise ValueError("a bug in the step")
        return band_step(4)(case)

    report = run_evaluation(flaky, "flaky", dataset, now=Clock(), **dirs)
    h = report["header"]
    assert (h["answered"], h["errors"]) == (1, 2)
    assert report["summary"]["urgency"]["all"] == {"n": 1, "exact": 1.0, "within_one": 1.0}
    errors = {e["case_id"]: e for e in report["errors"]}
    assert errors["case_b"]["call_failure"] is True
    assert errors["case_c"]["call_failure"] is False
    md = (dirs["reports_dir"] / "2026-11-22_flaky.md").read_text(encoding="utf-8")
    assert "| case_b | RetriesExhausted | yes |" in md


def test_fallback_is_off_during_the_run_and_restored_after(dataset, dirs, monkeypatch):
    monkeypatch.setenv("MODEL_FALLBACK", "on")
    seen = []

    def step(case):
        seen.append(os.environ["MODEL_FALLBACK"])
        return band_step(3)(case)

    run_evaluation(step, "fallback_check", dataset, now=Clock(), **dirs)
    assert seen == ["off", "off", "off"]
    assert os.environ["MODEL_FALLBACK"] == "on"


def test_subset_run_gets_its_own_report(dataset, dirs):
    report = run_evaluation(band_step(3), "fixed_band", dataset, case_ids=["case_b"], now=Clock(), **dirs)
    assert report["header"]["subset"] == ["case_b"]
    assert report["header"]["cases_selected"] == 1
    assert report["paths"]["markdown"].endswith("2026-11-22_fixed_band_subset.md")


class BudgetedStep:
    """Spends $0.20 per case, like a model call would, through the real budget."""

    def __init__(self):
        self.seen = []

    def __call__(self, case):
        models.current_budget().check()
        self.seen.append(case.id)
        models.current_budget().records.append(models.CallRecord("openai", "gpt-6-luna", 1, 0.0, cost_usd=0.20))
        return band_step(4)(case)


def test_spend_cap_stops_the_run_cleanly_and_resume_finishes_it(dataset, dirs):
    clock = Clock()
    step = BudgetedStep()

    first = run_evaluation(step, "paid", dataset, max_cost_usd=0.30, now=clock, **dirs)
    h = first["header"]
    assert h["status"] == "stopped" and "Spend cap reached" in h["stop_reason"]
    assert (h["answered"], h["not_run"]) == (2, 1)        # $0.20 + $0.20 passes $0.30, so case 3 is refused
    assert step.seen == ["case_a", "case_b"]
    md = (dirs["reports_dir"] / "2026-11-22_paid.md").read_text(encoding="utf-8")
    assert "Stopped: Spend cap reached" in md

    with pytest.raises(RunInProgress, match="2 of 3 cases answered"):
        run_evaluation(step, "paid", dataset, now=clock, **dirs)   # no silent restart

    second = run_evaluation(step, "paid", dataset, resume=True, max_cost_usd=1.00, now=clock, **dirs)
    h = second["header"]
    assert h["status"] == "complete" and h["answered"] == 3 and h["not_run"] == 0
    assert step.seen == ["case_a", "case_b", "case_c"]    # answered cases were skipped
    assert h["resumed"] is True and len(h["resumed_at"]) == 1
    assert h["resumed_at"][0] > h["started_at"]
    assert h["spent_usd"] == pytest.approx(0.60)          # spend is kept across sessions
    assert second["model_calls"]["openai/gpt-6-luna"]["calls"] == 3
    md = (dirs["reports_dir"] / "2026-11-22_paid.md").read_text(encoding="utf-8")
    assert f"| Resumed | Yes, at {h['resumed_at'][0]} |" in md


def test_resume_retries_errors_but_skips_answered_cases(dataset, dirs):
    calls = []
    fail = {"case_b"}

    def step(case):
        calls.append(case.id)
        if case.id in fail:
            raise ModelRateLimitError("429")
        return band_step(4)(case)

    run_evaluation(step, "retry_errors", dataset, now=Clock(), **dirs)
    fail.clear()
    report = run_evaluation(step, "retry_errors", dataset, resume=True, now=Clock(), **dirs)
    assert calls == ["case_a", "case_b", "case_c", "case_b"]
    assert (report["header"]["answered"], report["header"]["errors"]) == (3, 0)


def test_resume_needs_something_to_resume(dataset, dirs):
    with pytest.raises(RunInProgress, match="no saved run"):
        run_evaluation(band_step(3), "nothing", dataset, resume=True, now=Clock(), **dirs)
    run_evaluation(band_step(3), "nothing", dataset, now=Clock(), **dirs)
    with pytest.raises(RunInProgress, match="already answered every case"):
        run_evaluation(band_step(3), "nothing", dataset, resume=True, now=Clock(), **dirs)


def test_fresh_discards_an_unfinished_run(dataset, dirs):
    run_evaluation(BudgetedStep(), "paid", dataset, max_cost_usd=0.10, now=Clock(), **dirs)
    report = run_evaluation(band_step(2), "paid", dataset, fresh=True, now=Clock(), **dirs)
    assert report["header"]["status"] == "complete" and report["header"]["resumed"] is False


def test_resume_refuses_a_changed_test_set(dataset, dirs):
    run_evaluation(BudgetedStep(), "paid", dataset, max_cost_usd=0.10, now=Clock(), **dirs)
    (dataset / "labels" / "case_a.json").write_text(make_label("case_a", band=5).model_dump_json(), encoding="utf-8")
    with pytest.raises(DatasetError, match="test set has changed"):
        run_evaluation(BudgetedStep(), "paid", dataset, resume=True, now=Clock(), **dirs)


def test_progress_is_saved_after_every_case(dataset, dirs):
    def crash_on_c(case):
        if case.id == "case_c":
            raise KeyboardInterrupt  # like pressing Ctrl+C mid-run
        return band_step(4)(case)

    with pytest.raises(KeyboardInterrupt):
        run_evaluation(crash_on_c, "crash", dataset, now=Clock(), **dirs)
    state = json.loads((dirs["state_dir"] / "crash.json").read_text(encoding="utf-8"))
    assert sorted(state["rows"]) == ["case_a", "case_b"]
    report = run_evaluation(band_step(4), "crash", dataset, resume=True, now=Clock(), **dirs)
    assert report["header"]["answered"] == 3


def test_step_must_return_step_output(dataset, dirs):
    report = run_evaluation(lambda case: {"urgency": 3}, "wrong_type", dataset, now=Clock(), **dirs)
    assert report["errors"][0]["type"] == "TypeError"


def test_report_shows_the_test_set_path_relative_to_the_repo():
    from packs.council_complaints import DATA_DIR
    assert evaluation._display_path(DATA_DIR) == "data/council_complaints"


# ---- Baselines --------------------------------------------------------------------------

def test_keyword_urgency_baseline():
    from packs.council_complaints.baselines import keyword_urgency

    def run(text):
        return keyword_urgency(Case(id="x", source_text=text, received_date="2026-11-01", channel="email")).triage

    assert run("We will be sleeping rough tonight.").urgency_band == 5
    assert run("My mother was injured on the stairs.").urgency_band == 4
    assert run("There has been a leak for weeks.").urgency_band == 3
    assert run("Thank you for the new benches.").urgency_band == 1
    assert run("The parking meter is slow.").urgency_band == 2
    flags = run("Injured, and a leak too.").risk_flags
    assert flags == [RiskFlag(name="harm_or_vulnerability", source="rule"), RiskFlag(name="ongoing_problem", source="rule")]


def test_all_verified_baseline_finds_citations_across_line_breaks():
    from packs.council_complaints.baselines import all_verified

    text = "Under section\n512 of the Highways Act 1980 and the Made Up Act 2021, s.4, you must act."
    out = all_verified(Case(id="x", source_text=text, received_date="2026-11-01", channel="letter"))
    assert [c.raw_text for c in out.citations] == ["section\n512 of the Highways Act 1980", "Made Up Act 2021, s.4"]
    assert all(c.status == "verified" and c.is_grounded for c in out.citations)
    assert all(text[c.span.start:c.span.end] == c.raw_text for c in out.citations)
