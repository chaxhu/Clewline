# Council complaints test set (F2)

There are 20 synthetic UK council complaints, each with labelled answers. Every person, address, council, phone number and reference number is invented. The councils are Harrowfield, Eastmoor, Kelsbridge and Wyncombe. The postcode areas HF, EQ, KZ and WQ are not real UK postcode areas. Phone numbers use the Ofcom drama range (07700 900xxx).

## Layout

```
cases/case_XXX.json    the Case only (id, text, date, channel). Steps read this.
labels/case_XXX.json   the CaseLabel (issues, urgency band, citations). Only the evaluator reads this.
```

The letters and labels are written once in [scripts/build_test_set.py](../../scripts/build_test_set.py). Each label stores the exact words it refers to, and the script finds those words in the letter to work out the character span. To change the set, edit that script and run:

```bash
uv run python scripts/build_test_set.py
uv run pytest tests/test_dataset.py
```

## How the mix was chosen

| Dimension | Mix | Why |
| --- | --- | --- |
| Style | 10 short human letters, 10 long AI-style letters | The PRD's core problem is long AI-written letters. Short ones check that the system does not over-read simple cases. |
| Urgency band | 1: 3, 2: 5, 3: 6, 4: 4, 5: 2 | Real complaint queues are mostly routine. Every band is present, so accuracy per band can be measured. |
| Issues per case | 11 cases with 1 issue, 9 with 2 (29 in total) | Win 2 must split letters into issues, so about half of the letters have more than one. |
| Citations | 39 in total: 21 verified, 10 not_found, 8 needs_review | Just over half are real, so a detector that says "fake" every time scores badly. |
| Cases with no citations | 5 (all short human letters) | Checks that the extractor does not invent citations. |
| Channel | email, web_form, letter, phone | Covers every channel the schema allows. |

Deliberate traps:
- **case_020** is long, dramatic and uses words like "urgent", "distressing" and "unacceptable", but it is a band 1 website gripe. A keyword-based scorer should get it wrong.
- **case_014, case_018**: a real section is cited for the wrong purpose. EPA 1990 s.89 is about litter, but case_018 uses it for missed recycling. Labels record whether the law exists, not whether it fits the argument, so these are still `verified`.
- **case_016**: "section 149 of the Equality Act 2012". The act is real but the year is wrong (it is 2010).
- **Line breaks inside citations**: several AI-style citations wrap across lines, for example "section 11 of the\nLandlord and Tenant Act 1985". The extractor must cope with that.
- The same fake act appears in more than one letter (Council Accountability Act 2019 in case_009 and case_018), as a hallucination might.

## How each citation was labelled

The three labels follow the PRD:
- **verified**: the act exists and the cited section exists.
- **not_found**: no act with that title exists.
- **needs_review**: the act exists, but the cited section does not, or the citation is wrong in a way a human should look at.

Every row below was checked on legislation.gov.uk on 20 Nov 2026.
- **verified** rows: the section page loaded and showed the heading given.
- **needs_review** rows: the section page returned 404.
- **not_found** rows: a title search on legislation.gov.uk returned no results.

| Case | Citation as written | Label | Why |
| --- | --- | --- | --- |
| 003 | section 41 of the Highways Act 1980 | verified | Real: "Duty to maintain highways maintainable at public expense". |
| 006 | Environmental Protection Act 1990 s79 | verified | Real: "Statutory nuisances and inspections therefor". |
| 007 | section 11 of the Local Government Finance Act 1992 | verified | Real: "Discounts", which covers the single person discount. |
| 008 | Housing Act 1996 section 188 | verified | Real: "Interim duty to accommodate in case of apparent priority need". |
| 009 | Council Accountability Act 2019 | not_found | Invented. Title search found no act. |
| 010 | section 11 of the Landlord and Tenant Act 1985 | verified | Real: "Repairing obligations in short leases". |
| 010 | section 9A of the Landlord and Tenant Act 1985 | verified | Real: "Fitness for human habitation of dwellings in England", added by the Homes (Fitness for Human Habitation) Act 2018. |
| 010 | Residential Damp Prevention Act 2021 | not_found | Invented. Title search found no act. It sounds plausible because of real debate on damp and mould. |
| 010 | section 48 of the Landlord and Tenant Act 1985 | needs_review | The act is real, but section 48 returns 404. The claimed rent-reduction right is invented. |
| 011 | section 20 of the Equality Act 2010 | verified | Real: "Duty to make adjustments". |
| 011 | section 149 of the Equality Act 2010 | verified | Real: "Public sector equality duty". |
| 011 | section 412 of the Equality Act 2010 | needs_review | The act is real, but it ends at section 218 and section 412 returns 404. |
| 011 | Public Services Fairness Act 2016 | not_found | Invented. Title search found no act. |
| 012 | section 9 of the Care Act 2014 | verified | Real: "Assessment of an adult's needs for care and support". |
| 012 | section 150 of the Care Act 2014 | needs_review | The act is real, but section 150 returns 404. The "28 day maximum" is invented. |
| 012 | Local Authority Response Times Act 2020 | not_found | Invented. Title search found no act. |
| 012 | section 6 of the Human Rights Act 1998 | verified | Real: "Acts of public authorities". |
| 013 | section 1 of the Freedom of Information Act 2000 | verified | Real: "General right of access to information held by public authorities". |
| 013 | section 94 of the Freedom of Information Act 2000 | needs_review | The act is real, but section 94 returns 404. The weekly fixed penalty is invented. |
| 014 | Highways Act 1980, section 41 | verified | Real, as in case 003. Written in a different form on purpose. |
| 014 | section 512 of the Highways Act 1980 | needs_review | The act is real, but section 512 returns 404. The 48-hour rule is invented. |
| 014 | Highways Pothole Compensation Act 2018 | not_found | Invented. A title search for "Pothole Compensation" found no act. |
| 014 | Section 89 of the Environmental Protection Act 1990 | verified | Real: "Duty to keep land and highways clear of litter etc.". |
| 015 | section 79 of the Environmental Protection Act 1990 | verified | Real, as in case 006. |
| 015 | section 104 of the Anti-social Behaviour, Crime and Policing Act 2014 | verified | Real: "Review of response to complaints" (the Community Trigger). |
| 015 | section 181 of the Environmental Protection Act 1990 | needs_review | The act is real, but section 181 returns 404. The ban on car repairs is invented. |
| 015 | Tenants' Bill of Rights Act 2022 | not_found | Invented. Title search found no act. |
| 016 | section 188 of the Housing Act 1996 | verified | Real, as in case 008. |
| 016 | section 247 of the Housing Act 1996 | needs_review | The act is real, but section 247 returns 404. The six-week B&B limit for families does exist, but it is in a statutory instrument, not in this section. A human should look at it. |
| 016 | section 17 of the Children Act 1989 | verified | Real: "Provision of services for children in need, their families and others". |
| 016 | section 149 of the Equality Act 2012 | needs_review | No "Equality Act 2012" exists; only 2012 regulations made under the 2010 Act. It clearly means the real Equality Act 2010 s.149, so it is a wrong year on a real act rather than an invented act. A human should confirm. |
| 017 | Local Government Finance Act 1992 (section 11) | verified | Real, as in case 007. |
| 017 | Local Authority Response Times Act 2020 | not_found | Invented, as in case 012. |
| 017 | section 26 of the Local Government Act 1974 | verified | Real: "Matters subject to investigation" (the Ombudsman's remit). |
| 018 | Waste Collection Standards Act 2017 | not_found | Invented. Title search found no act. |
| 018 | section 89 of the Environmental Protection Act 1990 | verified | Real, as in case 014. It is used for the wrong purpose, but the law exists. |
| 018 | Council Accountability Act 2019 | not_found | Invented, as in case 009. |
| 020 | Human Rights Act 1998, section 6 | verified | Real, as in case 012. |
| 020 | Public Services Fairness Act 2016 | not_found | Invented, as in case 011. |

## Labels to check

These are the judgement calls where you might disagree:
1. **case_016, Equality Act 2012**: labelled `needs_review`. You could argue for `not_found`, because no act has that exact title.
2. **case_016, Housing Act 1996 s.247**: labelled `needs_review`. The rule it states is roughly true, but it sits in the wrong place.
3. **case_001**: band 4 rather than 5. There is no heating with a baby, but a plug-in heater is in use.
4. **case_003**: band 3 rather than 4. Someone has already been injured, but no vulnerable person is named.
