# PRD: Governed Agentic Casework Engine

Draft v0.1, 18 Nov 2026. Companion to the rationale doc, Governed Agentic AI Project: Rationale and Research.

## Summary

We are building a Python engine that handles incoming cases with a mix of rules, risk scoring and AI agents, and pauses for a human before any decision goes out. Every step is traced, costed and measurable. The first domain is council complaints, and the engine is designed so other industries can plug in later as domain packs.

The work is delivered as a ladder of small wins. Each win works on its own, can be posted or shown in a portfolio, and becomes a building block for the next. This PRD covers the shared foundations and wins 1 to 3 in detail, and wins 4 to 8 in outline.

## Problem

Public bodies and regulated businesses are receiving more cases, and the cases are longer and messier because people now write them with AI. Some cite laws that do not exist. Staff spend time untangling letters instead of making decisions.

AI could help, but most agentic AI projects stall or get cancelled because nobody can show what the agent did, what it cost, or whether it was right. The real gap is not a smarter model. It is a controlled way to use one.

## Goals

1. Learn agentic engineering hands-on, with a focus on AI governance.
2. Build a working casework flow where AI does the reading and checking, and a human makes the final call.
3. Make every AI action visible: what happened, why, how long it took and what it cost.
4. Measure quality against a labelled test set, so claims about accuracy are backed by numbers.
5. Ship small wins often, each with a short demo or write-up.

## Non-goals (for now)

- Real personal data. All cases are synthetic.
- A production deployment for a real organisation.
- Self-hosted models. Models are API only: OpenAI, plus Gemini and Groq free tiers.
- A polished front end. Streamlit is enough.
- The second domain pack. The boundary for it is designed in, but the pack itself is deferred.

## Users

| User | What they need |
| --- | --- |
| Caseworker | A clear summary of each complaint, its separate issues, flagged risks and a draft reply they can approve or edit |
| Team lead | A view of the backlog, urgent cases and where the AI is being overruled |
| Governance or audit reviewer | A full record of what the system did for any case, plus cost and accuracy figures |
| Builder (you) | Fast feedback on whether a change made things better or worse |

## Success measures

| Measure | How it is checked |
| --- | --- |
| Citation check accuracy | Share of real and fake citations correctly labelled on the test set |
| Issue extraction quality | Precision and recall of extracted issues against labelled answers |
| Triage accuracy | Share of cases given the correct urgency band |
| Grounding | Share of extracted items that point back to their source text |
| Cost per case | Total model cost per case, from Langfuse |
| Time per case | End-to-end run time, from Langfuse |
| Human override rate | Share of AI drafts the caseworker edits or rejects |
| Traceability | Every case run has a complete trace, with no missing steps |

Target numbers are set after the first baseline run, not guessed up front.

## Build order

We prove value first, then wrap it in the engine. Foundations come first, then two standalone wins that need no engine, then a thin end-to-end flow, which later wins thicken.

| Stage | What it delivers | Showable result |
| --- | --- | --- |
| Foundations | Case schema, synthetic test set, tracing, repo layout | Repo with a clean README and first traces |
| Win 1 | Fake-law detector | Post: catching made-up laws in AI-written complaints |
| Win 2 | Issue splitter and triage scorer | Post: accuracy and cost across three model providers |
| Win 3 | Walking skeleton of the engine | Demo: a case flows through and pauses for a human |
| Wins 4 to 8 | Governed tools, sign-off screen, dashboard, transparency record, second pack | One post or demo each |

## Foundations

**F1. Case schema.** Pydantic models define a `Case` (id, source text, received date, channel), `Issue` (summary, category, source span), `Citation` (raw text, normalised reference, status) and `TriageResult` (urgency band, risk flags, reasons). Every step reads and writes these models, so bad data is caught at the boundary.

**F2. Synthetic test set.** Start small, with about 15 to 20 synthetic council complaints, and grow it as each win needs, mixing short human-style letters and long AI-style letters. Some contain fake or misquoted legislation. Each has labelled answers: the issues, the urgency band and the true status of every citation. No real personal data is used.

**F3. Tracing from day one.** Langfuse runs locally with Docker. Every function that calls a model is wrapped with `@observe()`, so cost, timing, inputs and outputs are recorded from the first win.

**F4. Model access.** One small wrapper picks a provider (OpenAI, Gemini or Groq) through LangChain, so any step can be rerun on another provider by changing one setting. API keys live in a `.env` file that is never committed.

**F5. Evaluation runner.** A pytest-based runner scores any step against the test set and writes results to a dated report, so every change can be compared with the last.

## Win 1: Fake-law detector

**Goal.** Find every piece of legislation cited in a complaint and check whether it exists.

**Requirements**

1. Extract citations from the text with LangExtract, each linked to its exact position in the source.
2. Normalise each citation to a standard form, such as act name, year and section.
3. Check each one against legislation.gov.uk using httpx, with timeouts and caching.
4. Label each citation as verified, not found, or needs review (for example, the act exists but the section does not).
5. Output a Pydantic report plus an HTML view highlighting each citation in the original text.

**Done when.** It runs on the full test set, citation accuracy is reported, and a short demo or post is ready.

**Governance angle.** The system checks claims rather than generating them, and it marks uncertain cases for a human instead of guessing.

## Win 2: Issue splitter and triage scorer

**Goal.** Break a long complaint into its separate issues and give it an urgency band with reasons.

**Requirements**

1. Extract issues with LangExtract, each with a category and a link to its source text. Items with no source link are flagged.
2. Score urgency from 1 to 5 with structured output, plus rule-based risk flags (for example, vulnerability or safety words).
3. Give a short reason for every score, so a human can challenge it.
4. Run the same step on OpenAI, Gemini and Groq, and compare accuracy, cost and speed.

**Done when.** A comparison table across the three providers is published, with the evaluation report in the repo.

**Governance angle.** Measuring before automating: no step is trusted until its accuracy and cost are known.

## Win 3: Walking skeleton

**Goal.** Connect wins 1 and 2 into a single LangGraph workflow that runs end to end and pauses for a human.

**Flow**

1. Intake: validate the case and check for personal data.
2. Triage: run the win 2 scorer, then route by risk using a conditional edge.
3. Checks: run the win 1 citation checker.
4. Draft: produce a short summary and draft reply.
5. Human pause: `interrupt()` stops the workflow until a person approves, edits or rejects.
6. Close: record the outcome.

**Requirements**

1. State is saved after every step with the SQLite checkpointer, so a paused case survives a restart.
2. Each case has its own `thread_id` and a complete Langfuse trace.
3. The human decision is stored as a Langfuse score on the trace.
4. A simple command-line or Streamlit trigger is enough at this stage.

**Done when.** A demo shows a case flowing through, pausing, resuming after approval, and the full trace in Langfuse.

## Wins 4 to 8 (outline)

| Win | What it adds | Done when |
| --- | --- | --- |
| 4. Governed agent | The agent picks tools only from an approved list; a policy guard blocks and logs anything else | Demo of a forbidden action being stopped, visible in the trace |
| 5. Human sign-off screen | Streamlit screen to approve, edit or reject drafts; edits are saved back into the test set | Before and after quality shown as humans correct the agent |
| 6. Governance dashboard | Cost per case, time per case, override rate and failure types, pulled from Langfuse | Dashboard screenshot plus a short write-up |
| 7. Transparency record | An ATRS-style record generated from the logs and test results | A filled-in record produced by the system itself |
| 8. Second domain pack | A new pack folder for another industry, using the same engine unchanged | The same flow runs on a new case type |

Each of these gets its own detailed section in this PRD once the win before it is done.

### Possible later win: more free providers and rate-limit control

Paused on 22 Nov 2026 to finish the foundations. Today the model wrapper has OpenAI (default), Gemini (fallback) and Mistral (off by default), with simple retries and a spend cap. This win would add:

- **More free providers** through one OpenAI-compatible adapter (`ChatOpenAI` with a `base_url`): Groq, Cerebras and OpenRouter's `:free` models. Model ids come from each provider's `/models` endpoint, never guessed.
- **An ordered fallback chain** from `.env`, for example `MODEL_FALLBACK_CHAIN=openai,gemini,groq`, skipping providers without a key. Every hop is recorded in the trace.
- **Pacing** to stay about 20% under each provider's free-tier requests and tokens per minute, with one shared limiter per provider.
- **Daily quotas** tracked in a local SQLite file, with a clear `QuotaExhausted` error before a call we know will fail, and an evaluation pre-flight that says how many cases fit today.
- **A data and terms table** per provider: free limits, whether free prompts may be used for training, company country, and the date checked.

What we found when we looked (22 Nov 2026):
- Groq and Cerebras both retired Llama 3.3 70B. Their large free model is now `gpt-oss-120b`.
- Cerebras's free tier is a $5 trial that needs a card and lasts 30 days.
- OpenRouter's free models allow 50 requests a day, or 1,000 once $10 of credit has been bought.
- Mistral's free mode trains on prompts unless you opt out.

## Domain pack boundary

Everything industry-specific lives in one folder per domain, so the engine never hard-codes council details. A pack holds:

- **Policy:** rules, deadlines and categories.
- **Risk rules:** what makes a case urgent.
- **Tools:** domain lookups, such as the legislation checker.
- **Prompts:** extraction examples and reply style.
- **Test set:** labelled sample cases.

## Repository layout

One GitHub repository, one folder per win, each with its own README. A tagged release marks each finished win.

```
governed-casework/
  core/            schema, model wrapper, tracing, evaluation runner
  engine/          LangGraph workflow (from win 3)
  packs/
    council_complaints/
  wins/
    01_fake_law_detector/
    02_issue_triage/
    03_walking_skeleton/
  ui/              Streamlit screens (from win 5)
  data/            synthetic test sets
  reports/         dated evaluation results
  docker-compose.yml   local Langfuse
```

## Tech stack

Python 3.11+, Pydantic, LangChain, LangGraph with the SQLite checkpointer, LangExtract, Langfuse (self-hosted), httpx, pytest and Streamlit. Models: OpenAI, Gemini and Groq through APIs. What each library does is explained in the Toolkit section of the rationale doc.

## Governance requirements (apply to every win)

1. No real personal data, ever.
2. Every model call is traced with inputs, outputs, timing and cost.
3. Every extracted fact links back to its source text, or is flagged.
4. No decision leaves the system without human approval.
5. Every step has an evaluation score before it is called done.
6. Check each provider's data terms, especially on free tiers, before sending any data.

## Risks

| Risk | Mitigation |
| --- | --- |
| Free-tier rate limits slow evaluation | Cache results; keep the test set small at first |
| Synthetic data is too clean | Write messy, long, AI-style letters on purpose, including fake citations |
| legislation.gov.uk lookups are slow or brittle | Cache responses and allow a needs review label |
| Libraries hide how things work | Read the Toolkit notes; inspect Langfuse traces after each run |
| Scope creep | Detailed scope only one win ahead |

## Decisions on open questions (18 Nov 2026)

| Question | Decision |
| --- | --- |
| First test set size | Start small (about 15 to 20 cases) and grow it |
| Default provider | Gemini free tier for daily development; OpenAI credit (about $5) kept for provider comparisons and final evaluation runs |
| Where to post | A personal blog for full write-ups, plus a short LinkedIn post per win |
