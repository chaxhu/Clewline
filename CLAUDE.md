# Governed Agentic Casework Engine

## Purpose
A learning project in agentic engineering with a focus on AI governance.
We build a Python engine that handles incoming cases (first domain: UK council
complaints) with rules, risk scoring and AI agents, and pauses for a human
before any decision goes out. Every step is traced, costed and measured.
The full spec is in docs/PRD.md. Read it before planning any work.

## About me
I am the builder and I am learning as I go. I have an MSc in Data Science
with AI and I am comfortable in Python. I am newer to LangChain, LangGraph,
LangExtract and Langfuse.
- Explain what each library call does the first time you use it.
- Prefer clear, simple code over clever code.
- When there is a design choice, give me two options and a recommendation.
- I learn best with analogies and visual explanations.

## How we work
- The project is a ladder of small wins. Only work on the current win.
- Always plan first. Show the plan and wait for my approval before coding.
- Build in small steps. Run tests after each step.
- Commit after each working step with a clear message.
- Do not add a new library without telling me what it does and why we need it.
- Do not refactor earlier wins unless I ask.
- If something is unclear in the PRD, ask me instead of guessing.

## Stack
- Python 3.11+, managed with uv
- Pydantic for all data shapes
- LangChain for model access and tools
- LangGraph with the SQLite checkpointer for the workflow (from win 3)
- LangExtract for extraction with source grounding
- Langfuse (self-hosted with Docker) for tracing, cost and scores
- httpx for web calls, pytest for tests and evaluation, Streamlit for screens
- Models: OpenAI gpt-6-luna by default (cheapest model with structured
  output), Gemini as the fallback for call failures, Mistral available but
  off. The fallback is off in evaluation runs. Every run has a spend cap
  (MAX_RUN_COST_USD, default $0.50).

## Repository layout
- core/      schema, model wrapper, tracing, evaluation runner
- engine/    LangGraph workflow (from win 3)
- packs/     one folder per domain (packs/council_complaints first)
- wins/      one folder per win, each with its own README
- ui/        Streamlit screens (from win 5)
- data/      synthetic test sets
- reports/   dated evaluation results
- docs/      PRD, learning notes, blog drafts

## Governance rules (never break these)
1. No real personal data. All cases are synthetic.
2. Every model call is traced in Langfuse with inputs, outputs, timing and cost.
3. Every extracted fact links to its source text, or is flagged as ungrounded.
4. No decision leaves the system without human approval.
5. No step is called done until it has an evaluation score.
6. API keys live only in .env, which is in .gitignore. Never print or commit them.
7. Nothing domain-specific goes in core/ or engine/. It goes in packs/.

## Writing style for READMEs, docs and blog drafts
- Simple, flowing, easy to read on first pass.
- No em dashes anywhere.
- Avoid words like delve, leverage, seamless, pivotal, underscore, robust.
- Short sentences, plain words, concrete numbers.

## Definition of done for every win
- Code works and tests pass
- Evaluation run saved in reports/ with a date
- Win README: what it does, how to run it, results, what I learned
- Learning notes in docs/learning/ explaining each library used
- Short blog draft in docs/blog/