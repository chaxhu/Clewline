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

## Tracing setup (Langfuse, local)

Langfuse records every step the system runs: inputs, outputs, timing and, later, model cost. It runs on your machine in Docker. Give Docker Desktop at least 4 GB of memory.

**1. Generate the server secrets** (only needed once):

```bash
uv run python scripts/generate_secrets.py
```

This creates `.env` from `.env.example` and fills every `change-me` with a random value. It prints only the names of the secrets, never the values.

**2. Start Langfuse:**

```bash
docker compose up -d
docker compose ps        # wait until langfuse-web shows "Up" (about 1 to 2 minutes the first time)
```

**3. Create an account, a project and API keys** at http://localhost:3000:
1. Click **Sign up**. Use any name, email and password. The account exists only in your local database, so the email is never checked.
2. Create an **organisation** (for example `clewline`). You can skip inviting members.
3. Create a **project** (for example `council-complaints`).
4. Open the project's **Settings > API Keys** and click **Create new API keys**.
5. Copy the keys into `.env`. The secret key is shown only once.
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_BASE_URL=http://localhost:3000
   ```

**4. Send a test trace:**

```bash
uv run python scripts/send_test_trace.py
```

It prints a link. Open it, or go to **Tracing** in the left menu. You should see one trace called `test_trace_pipeline`, with one span called `count_words` nested inside it.

**Troubleshooting on Windows.** If `send_test_trace.py` says it could not authenticate:
- Read the error line it prints. A refused connection or timeout means the address is wrong or Langfuse is not up yet. `401 Unauthorized` means the keys are wrong.
- Set `LANGFUSE_BASE_URL=http://127.0.0.1:3000` in `.env`. On Windows, `localhost` can resolve to the IPv6 address `::1` first, but Docker only publishes the port on IPv4 `127.0.0.1`.
- Check that both keys come from the same project, and from this local Langfuse rather than Langfuse Cloud. A public key from one project with a secret key from another will be rejected.
- Run `docker compose ps` and make sure `langfuse-web` is running.

**What every trace is tagged with.** [core/tracing.py](core/tracing.py) sets three tags before the Langfuse client starts:
- service name `clewline`
- environment `dev`
- release: the current git commit, for example `dc5cec8`, with `-dirty` added if there are uncommitted changes

These tags show which code produced each trace. To override them, put `OTEL_SERVICE_NAME`, `LANGFUSE_TRACING_ENVIRONMENT` or `LANGFUSE_RELEASE` in `.env`.

To stop Langfuse, run `docker compose down`. Your data is kept. `docker compose down -v` deletes it.

## Models

```python
from core.models import get_chat_model

llm = get_chat_model()            # Gemini by default (MODEL_PROVIDER in .env)
llm = get_chat_model("openai")    # the same code on another provider
print(llm.invoke("Hello").text)
```

Every model it returns is already connected to Langfuse, so each call is traced with tokens and cost. Model names are set in `.env` (`GEMINI_MODEL`, `OPENAI_MODEL`).

```bash
uv run pytest              # unit tests only: offline, nothing traced
uv run pytest -m live -s   # one real, traced call per provider whose key is set
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
