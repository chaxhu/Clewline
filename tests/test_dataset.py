"""Checks on the synthetic test set in data/council_complaints/.

If someone edits a JSON file by hand and breaks a span or a label,
these tests fail before any evaluation runs on bad answers.
"""

import json
from pathlib import Path

import pytest

from core.schema import Case, CaseLabel
from packs.council_complaints.categories import CATEGORIES

DATA = Path(__file__).resolve().parent.parent / "data" / "council_complaints"
CASE_FILES = sorted((DATA / "cases").glob("*.json"))
LABEL_FILES = sorted((DATA / "labels").glob("*.json"))


def load_case(case_id: str) -> Case:
    return Case.model_validate_json((DATA / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))


def load_label(case_id: str) -> CaseLabel:
    return CaseLabel.model_validate_json((DATA / "labels" / f"{case_id}.json").read_text(encoding="utf-8"))


CASE_IDS = [p.stem for p in CASE_FILES]


def test_set_size_is_15_to_20():
    assert 15 <= len(CASE_FILES) <= 20


def test_every_case_has_exactly_one_label():
    assert [p.stem for p in CASE_FILES] == [p.stem for p in LABEL_FILES]


def test_case_files_contain_no_answers():
    """The answer keys must never appear in a file a step can read."""
    for path in CASE_FILES:
        keys = set(json.loads(path.read_text(encoding="utf-8")))
        assert keys == {"id", "source_text", "received_date", "channel"}, path.name


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_case_and_label_are_valid_and_match(case_id):
    case = load_case(case_id)
    label = load_label(case_id)
    assert case.id == case_id
    assert label.case_id == case_id


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_spans_point_at_the_right_text(case_id):
    text = load_case(case_id).source_text
    label = load_label(case_id)
    for issue in label.issues:
        assert issue.is_grounded, f"labelled issue has no span: {issue.summary}"
        assert issue.span.extract(text).strip()
    for citation in label.citations:
        assert citation.is_grounded, f"labelled citation has no span: {citation.raw_text}"
        assert citation.span.extract(text) == citation.raw_text


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_categories_are_from_the_pack(case_id):
    for issue in load_label(case_id).issues:
        assert issue.category in CATEGORIES


def test_mix_covers_every_band_and_every_status():
    labels = [load_label(cid) for cid in CASE_IDS]
    assert {lab.urgency_band for lab in labels} == {1, 2, 3, 4, 5}
    statuses = {c.status for lab in labels for c in lab.citations}
    assert statuses == {"verified", "not_found", "needs_review"}
    assert any(not lab.citations for lab in labels), "some cases should have no citations"
