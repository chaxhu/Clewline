"""Tests for core/schema.py: good data builds, bad data is rejected."""

from datetime import date

import pytest
from pydantic import ValidationError

from core.schema import Case, CaseLabel, Citation, Issue, RiskFlag, Span, TriageResult

TEXT = "My boiler has been broken for three weeks."


# ---------- Span ----------

def test_span_valid_and_extract():
    span = Span(start=3, end=9)
    assert span.extract(TEXT) == "boiler"


@pytest.mark.parametrize("start, end", [(5, 5), (9, 3), (-1, 4)])
def test_span_rejects_bad_ranges(start, end):
    with pytest.raises(ValidationError):
        Span(start=start, end=end)


def test_span_extract_past_end_of_text():
    with pytest.raises(ValueError):
        Span(start=0, end=999).extract(TEXT)


# ---------- Case ----------

def make_case(**overrides):
    data = {
        "id": "case_001",
        "source_text": TEXT,
        "received_date": "2026-11-01",
        "channel": "email",
    }
    data.update(overrides)
    return Case(**data)


def test_case_valid_parses_date_string():
    case = make_case()
    assert case.received_date == date(2026, 11, 1)


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_text": ""},
        {"source_text": "   \n "},
        {"id": ""},
        {"channel": "fax"},
        {"received_date": "not a date"},
        {"urgency": 3},  # unknown field
    ],
)
def test_case_rejects_bad_data(overrides):
    with pytest.raises(ValidationError):
        make_case(**overrides)


def test_case_missing_field():
    with pytest.raises(ValidationError):
        Case(id="x", source_text=TEXT, channel="email")


# ---------- Issue ----------

def test_issue_grounded_and_ungrounded():
    grounded = Issue(summary="Broken boiler", category="housing_repairs", span=Span(start=3, end=9))
    ungrounded = Issue(summary="Broken boiler", category="housing_repairs")
    assert grounded.is_grounded
    assert not ungrounded.is_grounded


@pytest.mark.parametrize("field", ["summary", "category"])
def test_issue_rejects_empty_strings(field):
    data = {"summary": "Broken boiler", "category": "housing_repairs", field: ""}
    with pytest.raises(ValidationError):
        Issue(**data)


# ---------- Citation ----------

@pytest.mark.parametrize("status", ["verified", "not_found", "needs_review"])
def test_citation_accepts_each_status(status):
    c = Citation(raw_text="section 11", status=status, span=Span(start=0, end=10))
    assert c.status == status


def test_citation_rejects_unknown_status():
    with pytest.raises(ValidationError):
        Citation(raw_text="section 11", status="fake", span=Span(start=0, end=10))


def test_citation_grounded_and_ungrounded():
    grounded = Citation(raw_text="section 11", status="verified", span=Span(start=0, end=10))
    ungrounded = Citation(raw_text="section 11", status="verified")
    assert grounded.is_grounded
    assert not ungrounded.is_grounded


def test_citation_rejects_empty_raw_text():
    with pytest.raises(ValidationError):
        Citation(raw_text="", status="verified")


# ---------- RiskFlag ----------

@pytest.mark.parametrize("source", ["rule", "model"])
def test_risk_flag_accepts_each_source(source):
    assert RiskFlag(name="vulnerable_person", source=source).source == source


@pytest.mark.parametrize(
    "data",
    [
        {"name": "vulnerable_person", "source": "human"},  # unknown source
        {"name": "", "source": "rule"},  # empty name
        {"name": "vulnerable_person"},  # missing source
    ],
)
def test_risk_flag_rejects_bad_data(data):
    with pytest.raises(ValidationError):
        RiskFlag(**data)


# ---------- TriageResult ----------

def test_triage_valid():
    t = TriageResult(
        urgency_band=4,
        risk_flags=[
            RiskFlag(name="vulnerable_person", source="rule"),
            {"name": "safety_risk", "source": "model"},  # a plain dict is converted too
        ],
        reasons=["Baby in home"],
    )
    assert t.urgency_band == 4
    assert [f.source for f in t.risk_flags] == ["rule", "model"]


def test_triage_rejects_plain_string_flags():
    with pytest.raises(ValidationError):
        TriageResult(urgency_band=3, risk_flags=["vulnerable_person"], reasons=["x"])


@pytest.mark.parametrize("band", [0, 6, -1])
def test_triage_rejects_band_out_of_range(band):
    with pytest.raises(ValidationError):
        TriageResult(urgency_band=band, reasons=["x"])


def test_triage_requires_a_reason():
    with pytest.raises(ValidationError):
        TriageResult(urgency_band=3, reasons=[])


def test_round_trip_through_json():
    t = TriageResult(
        urgency_band=2, risk_flags=[RiskFlag(name="repeat_contact", source="rule")], reasons=["Routine"]
    )
    assert TriageResult.model_validate_json(t.model_dump_json()) == t


# ---------- CaseLabel ----------

def make_label(**overrides):
    data = {
        "case_id": "case_001",
        "issues": [{"summary": "Broken boiler", "category": "housing_repairs", "span": {"start": 3, "end": 9}}],
        "urgency_band": 3,
        "citations": [],
    }
    data.update(overrides)
    return CaseLabel(**data)


def test_case_label_valid():
    label = make_label()
    assert label.issues[0].span == Span(start=3, end=9)
    assert label.citations == []
    assert label.contested is False  # default


def test_case_label_contested_flag():
    assert make_label(contested=True).contested is True
    with pytest.raises(ValidationError):
        make_label(contested="maybe")


@pytest.mark.parametrize(
    "overrides",
    [
        {"case_id": ""},
        {"issues": []},  # every labelled case has at least one issue
        {"urgency_band": 0},
        {"citations": [{"raw_text": "s.11", "status": "maybe"}]},
        {"source_text": "answers must not travel with the text"},  # extra field
    ],
)
def test_case_label_rejects_bad_data(overrides):
    with pytest.raises(ValidationError):
        make_label(**overrides)
