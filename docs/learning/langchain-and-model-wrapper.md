# LangChain and our model wrapper

## What LangChain is

LangChain gives every chat model, from any provider, the same Python interface. `ChatOpenAI`, `ChatGoogleGenerativeAI` and `ChatMistralAI` all have `.invoke()`, `.with_structured_output()` and `.bind_tools()`, so code written for one works with the others.

Think of it as a universal travel adaptor. Each country (provider) has its own socket shape. The adaptor means your laptop (our code) plugs in the same way everywhere.

## What our wrapper adds

[core/models.py](../../core/models.py) has one function that every step calls:

```python
from core.models import get_chat_model

llm = get_chat_model()            # OpenAI gpt-6-luna by default (MODEL_PROVIDER in .env)
llm = get_chat_model("gemini")    # same code, another provider
reply = llm.invoke("Hello")       # reply.text is the answer
```

On top of plain LangChain it adds four things:

1. **Tracing.** The Langfuse callback is attached, so every call is a generation in Langfuse with tokens and cost.
2. **Retries.** 429, 5xx, timeouts and dropped connections are retried up to 4 times, waiting 1s, 2s, 4s and so on with random jitter, or exactly as long as the server's `Retry-After` says. 400, 401, 403 and 404 are never retried, because trying again would give the same answer. The providers' own retries are switched off (`max_retries=0`) so only ours run.
3. **Spend cap.** Each call's cost is worked out from its tokens and the price table. Once a run reaches `MAX_RUN_COST_USD` (default $0.50), the next call is refused with `SpendCapReached` before it is sent.
4. **Fallback.** If an OpenAI call still fails after its retries, the same request goes to Gemini. The trace shows the failed call, a `model_fallback` event and the Gemini call. Evaluation runs switch the fallback off, so every score comes from one model.

## The LangChain calls we use

- `ChatOpenAI(model=..., api_key=..., temperature=..., timeout=..., max_retries=0, metadata=...)` builds a model. The others take the same kind of settings.
- `model.invoke(prompt)` sends one request and returns an `AIMessage`. `.text` is the answer and `.usage_metadata` holds the token counts.
- `primary.with_fallbacks([backup], exceptions_to_handle=...)` tries the primary, and on one of the listed errors sends the same input to the backup.
- `chain.with_config(callbacks=[handler])` attaches the Langfuse handler to the whole chain, so the failed call, the event and the answer land in one trace.
- `BaseCallbackHandler.on_llm_error` is a hook LangChain calls when a model call raises. We use it to record the fallback.

## How the retry loop gets in

Every LangChain chat model sends its requests through one private method, `_generate`. Our wrapper makes a subclass of the provider's class that overrides `_generate` with a retry loop and the spend check, then calls the original. Because every public method goes through `_generate`, `.invoke()`, `.with_structured_output()` and `.bind_tools()` all get retries for free. The subclass keeps the original class name, so Langfuse still shows `ChatOpenAI`.

## Gotchas we hit

- **`gpt-6-luna` rejects `temperature=0`.** It is a reasoning model that only accepts its default of 1. For that model we send no temperature, and the trace metadata says `temperature: model default (fixed)`. Two runs can give slightly different answers, so evaluations on it should be repeated.
- **Retries in two places.** Left alone, the OpenAI library retries by itself, so one call could be tried 4 x 3 times and the waits would be hidden. Setting the library's `max_retries=0` keeps the count honest.
- **The fallback must not hide bugs.** A bad request, a wrong key or a reply that does not parse would fail on Gemini too, so they never trigger it. Only call failures do.
- **Unknown prices.** A model missing from the price table is costed at a deliberately high price, with a warning, so the spend cap still protects you.

## Further reading

- LangChain chat models: https://docs.langchain.com/oss/python/langchain/models
- Fallbacks: https://python.langchain.com/docs/how_to/fallbacks/
