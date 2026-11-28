# Langfuse

## What it is

Langfuse records what an AI system did, step by step. For each run it stores the inputs, outputs, timing, tokens and cost, and shows them as a tree in a web page.

Think of it as the flight recorder in a plane. You do not look at it while things go well. When something goes wrong, or an auditor asks "what did the system do for case 16?", it has the whole story, in order, with timestamps.

We run it on our own machine in Docker (see [docker-compose.md](docker-compose.md)), so no complaint text leaves the laptop for tracing.

## The words it uses

| Word | Meaning | Example |
| --- | --- | --- |
| Trace | One whole run, the top of the tree | `evaluation_run` |
| Span (observation) | One step inside a trace | `eval_case`, `count_words` |
| Generation | A span that is a model call, with tokens and cost | `ChatOpenAI` |
| Event | A single moment, with no duration | `model_fallback` |
| Score | A number or label attached to a trace | a human approval (from Win 3) |

## How we use it

[core/tracing.py](../../core/tracing.py) is the only place that sets Langfuse up.

```python
from core.tracing import observe

@observe(name="count_words")
def count_words(text): ...
```

- `@observe()` records each call to the function: arguments in, return value out, start and end time. If a decorated function calls another decorated function, the inner one appears nested under the outer one.
- `get_langchain_handler()` returns a LangChain callback (`langfuse.langchain.CallbackHandler`). [core/models.py](../../core/models.py) attaches it to every chat model, so each model call becomes a generation with its tokens and cost.
- `flush()` sends anything still queued. The SDK sends traces in batches on a background thread, so a short script must flush before it exits or the last traces are lost.
- `check_connection()` asks the server whether our keys work, and prints the real error if not.

Every trace is tagged with a service name (`clewline`), an environment (`dev` or `eval`) and a release (the git commit, plus `-dirty` if there are uncommitted changes). The tags must be set as environment variables before the Langfuse client starts, because it reads them only once.

## Gotchas we hit

- **`localhost` on Windows.** `localhost` can resolve to the IPv6 address `::1` first, but Docker publishes the port on IPv4 only. Using `http://127.0.0.1:3000` fixed refused connections.
- **Keys from two projects.** A public key from one Langfuse project and a secret key from another give `401 Unauthorized`.
- **Tests must not send traces.** [tests/conftest.py](../../tests/conftest.py) sets `LANGFUSE_TRACING_ENABLED=false` for plain unit test runs, before any test module imports Langfuse. Live and eval runs keep tracing on, because every real model call must be traced (governance rule 2).
- **Metadata values are capped at 200 characters**, so long error messages are cut before they are attached.

## Further reading

- Langfuse Python SDK: https://langfuse.com/docs/observability/sdk/python/overview
- LangChain integration: https://langfuse.com/integrations/frameworks/langchain
- Self-hosting with Docker Compose: https://langfuse.com/self-hosting/deployment/docker-compose
