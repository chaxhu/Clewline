# Clewline

Governed agentic AI for casework. AI agents research each case, a human signs off every decision, and every step is traced, costed and evaluated.

The first domain is UK council complaints. All cases are synthetic.

## Setup

You need [uv](https://docs.astral.sh/uv/) and Docker Desktop.

```bash
uv sync                 # create .venv and install dependencies
cp .env.example .env    # then add your own keys
uv run pytest           # run the tests
```

## Layout

| Folder | What lives there |
| --- | --- |
| `core/` | Schema, model wrapper, tracing, evaluation runner. Nothing domain-specific. |
| `engine/` | LangGraph workflow (from win 3) |
| `packs/` | One folder per domain, starting with `packs/council_complaints/` |
| `wins/` | One folder per win, each with its own README |
| `ui/` | Streamlit screens (from win 5) |
| `data/` | Synthetic labelled test sets |
| `reports/` | Dated evaluation results |
| `docs/` | PRD, learning notes, blog drafts |

## Governance rules

1. No real personal data. All cases are synthetic.
2. Every model call is traced in Langfuse.
3. Every extracted fact links to its source text, or is flagged as ungrounded.
4. No decision leaves the system without human approval.
5. No step is called done until it has an evaluation score.
6. API keys live only in `.env`, which is never committed.
7. Nothing domain-specific goes in `core/` or `engine/`.

The full spec is in [docs/PRD.md](docs/PRD.md).
