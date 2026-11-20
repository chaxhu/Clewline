"""F1. Case schema: the data shapes every step reads and writes.

These models are the "customs desk" at every boundary. If a step produces
data with a missing field, a wrong type or an impossible value, Pydantic
raises a ValidationError straight away instead of letting bad data travel
further down the pipeline.

Nothing here is specific to council complaints (governance rule 7). For
example, Issue.category is a plain string; each domain pack defines its own
list of allowed categories.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base for all schema models.

    extra="forbid" means an unknown field is an error, not silently ignored.
    That catches typos such as "urgancy_band" and models inventing fields.
    """

    model_config = ConfigDict(extra="forbid")


class Span(StrictModel):
    """A character range in a case's source text, like Python slicing.

    text[span.start:span.end] gives the exact quoted words.
    """

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def end_after_start(self) -> "Span":
        if self.end <= self.start:
            raise ValueError(f"span end ({self.end}) must be greater than start ({self.start})")
        return self

    def extract(self, text: str) -> str:
        """Return the slice of text this span points to, or fail if it is out of range."""
        if self.end > len(text):
            raise ValueError(f"span end ({self.end}) is past the end of the text ({len(text)} chars)")
        return text[self.start : self.end]


Channel = Literal["email", "web_form", "letter", "phone"]


class Case(StrictModel):
    """One incoming case, exactly as received."""

    id: str = Field(min_length=1)
    source_text: str
    received_date: date
    channel: Channel

    @field_validator("source_text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_text must not be empty or only whitespace")
        return value


class Issue(StrictModel):
    """One separate problem raised in a case.

    span is None when the issue cannot be linked to the source text.
    Such an issue is "ungrounded" and must be flagged (governance rule 3).
    """

    summary: str = Field(min_length=1)
    category: str = Field(min_length=1)
    span: Span | None = None

    @property
    def is_grounded(self) -> bool:
        return self.span is not None


CitationStatus = Literal["verified", "not_found", "needs_review"]


class Citation(StrictModel):
    """A piece of legislation (or other authority) cited in a case.

    status:
      verified      the act and section exist
      not_found     the act does not exist
      needs_review  the act exists but the section or detail does not check out

    span is None when the citation cannot be linked to the source text.
    It is kept and flagged as ungrounded, never silently dropped.
    """

    raw_text: str = Field(min_length=1)
    normalised_ref: str | None = None
    status: CitationStatus
    span: Span | None = None

    @property
    def is_grounded(self) -> bool:
        return self.span is not None


RiskFlagSource = Literal["rule", "model"]


class RiskFlag(StrictModel):
    """One risk signal, and whether a fixed rule or a model raised it."""

    name: str = Field(min_length=1)
    source: RiskFlagSource


class TriageResult(StrictModel):
    """How urgent a case is, and why.

    Every score needs at least one reason, so a human can challenge it.
    """

    urgency_band: int = Field(ge=1, le=5)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    reasons: list[str] = Field(min_length=1)


class CaseLabel(StrictModel):
    """The human-labelled right answers for one Case.

    Labels live in a separate model and a separate file from the Case, so a
    step under test only ever receives the Case and cannot see the answers.
    Only the evaluation runner joins the two, by case_id.
    """

    case_id: str = Field(min_length=1)
    issues: list[Issue] = Field(min_length=1)
    urgency_band: int = Field(ge=1, le=5)
    citations: list[Citation] = Field(default_factory=list)
    # True when the urgency band is a judgement call between two neighbouring bands.
    # Evaluations should report exact and within-one-band accuracy, and may
    # show contested cases separately.
    contested: bool = False
    notes: str | None = None  # free-text labelling rationale for human reviewers
