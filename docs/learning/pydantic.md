# Pydantic

## What it is

Pydantic checks that data has the shape you said it would have. You describe the shape once, as a Python class, and Pydantic checks every value that goes into it.

Think of it as a customs desk at every border in the pipeline. A parcel (some data) arrives. The officer checks the label (the field names), the contents (the types) and the rules (for example "end must be after start"). If anything is wrong, the parcel is stopped at the desk with a clear note, instead of breaking something three steps later.

## How we use it

All our data shapes live in [core/schema.py](../../core/schema.py):

| Model | What it holds |
| --- | --- |
| `Case` | One complaint as received: id, text, date, channel |
| `Span` | A character range in the text, like Python slicing |
| `Issue` | One problem in the complaint, with its category and span |
| `Citation` | One law cited, its normalised form, its status and its span |
| `TriageResult` | Urgency band 1 to 5, risk flags and reasons |
| `CaseLabel` | The right answers for one case, kept in a separate file |
| `StepOutput` | What a step returns ([core/evaluation.py](../../core/evaluation.py)) |

Every step reads and writes these models, so bad data is caught at the boundary.

## The calls we use

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")   # an unknown field is an error, not ignored

class Span(StrictModel):
    start: int = Field(ge=0)                     # ge = "greater than or equal to"
    end: int = Field(ge=0)

    @model_validator(mode="after")               # runs after every field is checked
    def end_after_start(self):
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self
```

- `Field(ge=1, le=5)` sets limits on a number. `Field(min_length=1)` stops empty strings and lists.
- `@field_validator("source_text")` checks one field, for example "not only whitespace".
- `@model_validator(mode="after")` checks fields against each other.
- `Literal["verified", "not_found", "needs_review"]` allows only those exact strings.
- `Case.model_validate_json(text)` reads JSON and checks it in one go.
- `case.model_dump_json(indent=2)` writes a model back out as JSON.

## Gotchas we hit

- **Silent typos.** By default Pydantic ignores fields it does not know. A label file with `"urgancy_band"` would load fine and the real field would be missing. `extra="forbid"` on every model turns that into an error.
- **Labels next to cases.** If the right answers were fields on `Case`, a step could read them by accident. They live in `CaseLabel`, in a separate folder, and only the evaluation runner joins the two.
- **A missing span is not an empty span.** `span: Span | None = None` means "we could not link this to the text". We keep such items and flag them as ungrounded (governance rule 3), rather than inventing a span of zero length.

## Further reading

- Pydantic docs, Models: https://docs.pydantic.dev/latest/concepts/models/
- Pydantic docs, Validators: https://docs.pydantic.dev/latest/concepts/validators/
