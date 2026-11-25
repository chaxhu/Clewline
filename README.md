# Clewline

Clewline is a learning project in governed AI for casework. AI agents read each case and suggest what to do. A human signs off every decision before it goes out. Every step is traced, costed and scored against labelled answers.

The first domain is UK council complaints.

> **All data is synthetic.** Every complaint, name, address and council in this repo is invented. No real personal data is used anywhere.

## Status

- **Foundations: done.** A case schema, 20 labelled test complaints, local tracing with Langfuse, one switch between OpenAI and Gemini, and an evaluation runner that writes dated reports. 214 tests pass.
- **Next: Win 1, the fake-law detector.** It will check every law a complaint cites and label it as real, made up, or needing a human to review.

## First result

Before any AI, a simple keyword rule rates how urgent each test complaint is, on a scale of 1 to 5:

| Step | Exact band | Within one band |
| --- | --- | --- |
| Keyword rule (no AI) | 45% | 90% |

So it picks the exact band 45% of the time, and is at most one band off 90% of the time. This is the bar every AI step has to beat. Full report: [reports/2026-11-24_keyword_urgency.md](reports/2026-11-24_keyword_urgency.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/). No API keys are needed for this.

```bash
git clone https://github.com/chaxhu/Clewline.git
cd Clewline
uv sync                                             # install dependencies
uv run pytest                                       # 214 offline tests
uv run python scripts/run_eval.py keyword_urgency   # score the keyword rule and write a report
```

Without Langfuse keys, the last command prints an "Authentication error" warning. That only means tracing is off. The run still finishes and writes its report.

To make real model calls, copy `.env.example` to `.env` and add your own keys. To see traces, set up Langfuse as below. It needs Docker Desktop.

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

llm = get_chat_model()            # OpenAI by default (MODEL_PROVIDER in .env)
llm = get_chat_model("gemini")    # the same code on another provider
print(llm.invoke("Hello").text)
```

Every model it returns is already connected to Langfuse, so each call is traced with tokens and cost. Model names are set in `.env`.

Temperature is 0 by default, so runs repeat as closely as possible. `gpt-6-luna` is a reasoning model and rejects any temperature except its default of 1, so for that model we send none. Its trace metadata says `temperature: model default (fixed)`. Two runs on it can give slightly different answers.

| Provider | Default model | Role | Why this model |
| --- | --- | --- | --- |
| OpenAI | `gpt-6-luna` | Default | Cheapest current OpenAI model with structured outputs: $0.10 in, $0.50 out per 1M tokens (checked 22 Nov 2026). `gpt-5-nano` and `gpt-5-mini` shut down on 11 Dec 2026. |
| Gemini | `gemini-3.8-flash` | Fallback | Free tier. |
| Mistral | `ministral-8b-2512` | Off by default | The free plan allows 2 requests a minute on this model, and 0 on `mistral-small-2603`. |

### Retries

The provider libraries' own retries are switched off, so only ours run. A call is tried up to 4 times (`MODEL_MAX_ATTEMPTS`):
- **Retried:** 429 (rate limit), 5xx such as 503, timeouts and lost connections.
- **Never retried:** 400, 401, 403 and 404. Trying again would give the same answer.
- **Wait:** 1s, 2s, 4s and so on, up to 30s, with random jitter so retries do not all land at once. If the server sends `Retry-After`, we wait exactly that long instead. If it asks for more than 60s, we give up at once.
- **Giving up** raises `RetriesExhausted`, which names the provider, the model, the number of attempts and the reason.

### Spend cap

`MAX_RUN_COST_USD` (default `$0.50`) caps what one run may spend. Each call's cost is worked out from its token counts and the price table in [core/models.py](core/models.py). Once a run reaches the cap, the next call is refused with `SpendCapReached` before it is sent. An evaluation run then stops cleanly and can be resumed. A model missing from the price table is costed at a deliberately high price, with a warning, so the cap still protects you.

```bash
uv run pytest              # unit tests only: offline, nothing traced
uv run pytest -m live -s   # one real, traced call per provider whose key is set
```

### Fallback from OpenAI to Gemini

If an OpenAI call still fails after its retries, the same request goes to Gemini. Only call failures count: a rate limit (429), a server error (5xx), a timeout or a lost connection. A bad request, a wrong key, a reply that does not parse and the spend cap never trigger it, because another model would not fix those.

When a fallback happens, the trace shows it in three places:
- the failed OpenAI call, marked as an error
- a `model_fallback` event, with the reason (for example `rate_limit`)
- the Gemini call, with `provider: gemini` in its metadata

So a trace never says OpenAI answered when Gemini did.

**When it is on and off:**

| Run | Fallback | Why |
| --- | --- | --- |
| Normal use, scripts, the UI | On (`MODEL_FALLBACK=on`) | A case should not get stuck because of a short Gemini outage. |
| Evaluation runs (`pytest -m eval`) | Off | Every score must come from one model. A failed call is counted as an error, not as a wrong answer. |
| Live smoke tests (`pytest -m live`) | Off | Each test must prove that its own provider answered. |

To turn it off everywhere, set `MODEL_FALLBACK=off` in `.env`. A single step can also choose with `get_chat_model(fallback=False)`. If `GOOGLE_API_KEY` is not set, the fallback switches itself off with a warning.

## Evaluation

[core/evaluation.py](core/evaluation.py) scores any step against the labelled test set and writes a dated report to `reports/`. A step is any function that takes a `Case` and returns a `StepOutput`. It never sees the labels.

```bash
uv run pytest -m eval                                            # both baselines, full test set
uv run python scripts/run_eval.py keyword_urgency                # one step
uv run python scripts/run_eval.py keyword_urgency --cases case_001,case_003
uv run python scripts/run_eval.py keyword_urgency --limit 5
uv run python scripts/run_eval.py keyword_urgency --resume       # continue after a stop
uv run python scripts/run_eval.py keyword_urgency --fresh        # start again
uv run python scripts/run_eval.py keyword_urgency --max-cost 0.25
```

What every run does:
- **Fallback off.** Every score comes from one model.
- **Errors are not wrong answers.** If a step fails, for example a call that failed after all retries, the case is listed under Errors and left out of the scores.
- **Progress is saved after every case** in `.cache/eval_runs/`. If the spend cap stops a run, or it crashes, `--resume` carries on: it skips answered cases and tries failed ones again. Without `--resume` or `--fresh`, an unfinished run is never silently thrown away.
- **Subsets** (`--cases`, `--limit`) get their own report, `reports/<date>_<step>_subset.md`, so they never overwrite a full run.
- **The report header** gives the status, the environment (`eval`), the release (git commit), a fingerprint of the test set, the headline urgency score, the cases run, the models used, the fallback setting, the spend against the cap, and when the run started and was resumed. Two reports are only comparable when their fingerprints match.

What is scored, when a step returns it:

| Part | Scores |
| --- | --- |
| Urgency band | Exact and within one band, for all cases, then split into contested and not contested |
| Citations | Found (by overlapping text), status right, and recall per status (verified, not_found, needs_review) |
| Issues | Precision, recall and F1. A match needs the same category and overlapping text |
| Grounding | Share of predicted issues and citations that link to the source text |

The two baselines in [packs/council_complaints/baselines.py](packs/council_complaints/baselines.py) are the scores every AI step has to beat.

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
