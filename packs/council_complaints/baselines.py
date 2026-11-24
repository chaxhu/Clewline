"""Naive rule baselines: the scores any AI step has to beat.

They are deliberately simple, and they were written without tuning them on
the labels. Like every step, each one receives only the Case, never the answers.

  keyword_urgency  picks an urgency band from keywords.
  all_verified     finds anything that looks like "<Name> Act <year>" and calls
                   every one verified. It shows what "believe every citation" scores.
"""

import re

from core.evaluation import StepOutput
from core.schema import Case, Citation, RiskFlag, Span, TriageResult

# (band, risk flag, keywords). The highest band with a match wins.
URGENCY_RULES = [
    (5, "immediate_risk", ("tonight", "nowhere to sleep", "sleeping rough", "no heating", "gas leak",
                           "carbon monoxide", "collapse", "fire", "suicid", "self-harm")),
    (4, "harm_or_vulnerability", ("injur", "hospital", "unsafe", "dangerous", "asthma", "pregnan",
                                  "disabled", "wheelchair", "elderly", "vulnerable")),
    (3, "ongoing_problem", ("leak", "damp", "mould", "broken", "repair", "weeks", "months")),
]
LOW_PRIORITY = ("thank", "suggest", "compliment", "feedback")
DEFAULT_BAND = 2


def keyword_urgency(case: Case) -> StepOutput:
    text = case.source_text.lower()
    flags, reasons, band = [], [], None
    for rule_band, flag, keywords in URGENCY_RULES:
        hits = [k for k in keywords if k in text]
        if hits:
            band = band or rule_band  # rules are in falling order, so the first match is the highest
            flags.append(RiskFlag(name=flag, source="rule"))
            reasons.append(f"band {rule_band} keywords: {', '.join(hits)}")
    if band is None:
        low = [k for k in LOW_PRIORITY if k in text]
        band = 1 if low else DEFAULT_BAND
        reasons.append(f"low-priority keywords: {', '.join(low)}" if low else "no keywords matched, default band")
    return StepOutput(triage=TriageResult(urgency_band=band, risk_flags=flags, reasons=reasons))


# "section 12 of the", then a capitalised name ending in "Act 1990", then ", section 41" or " s.41".
# \s also matches line breaks, because letters wrap citations across lines.
_NAME_WORD = r"(?:[A-Z][A-Za-z()'-]*|and|of|the|for|on|to|in)"
ACT_PATTERN = re.compile(
    r"(?:[Ss]ection\s+\d+[A-Za-z]?(?:\(\d+\))?\s+of\s+the\s+)?"
    rf"[A-Z][A-Za-z()'-]*(?:\s+{_NAME_WORD})*\s+Act\s+\d{{4}}"
    r"(?:,?\s+(?:section|s\.)\s*\d+[A-Za-z]?(?:\(\d+\))?)?"
)


def all_verified(case: Case) -> StepOutput:
    citations = [
        Citation(raw_text=m.group(0), status="verified", span=Span(start=m.start(), end=m.end()))
        for m in ACT_PATTERN.finditer(case.source_text)
    ]
    return StepOutput(citations=citations)


# The steps scripts/run_eval.py can run, by name.
STEPS = {
    "keyword_urgency": keyword_urgency,
    "all_verified": all_verified,
}
