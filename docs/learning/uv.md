# uv

## What it is

uv installs Python packages and runs your code in the project's own environment. It does the jobs of `pip`, `venv` and `pip-tools` in one fast tool.

Think of it as a recipe card plus a sealed pantry. `pyproject.toml` is the recipe: the ingredients you asked for. `uv.lock` is the exact shopping receipt: every package and version that was actually bought, including the ones your ingredients needed. `.venv/` is the pantry where they are kept, separate from the rest of your computer.

## How we use it

```bash
uv sync                                   # make .venv match uv.lock exactly
uv run pytest                             # run a command inside .venv
uv run python scripts/run_eval.py ...     # same for any script
uv add langextract                        # add a dependency: updates pyproject.toml and uv.lock
uv add --dev pytest                       # a dependency only needed for development
```

- `uv run` checks that `.venv` matches the lock file before it runs anything, so you never run code against stale packages.
- `.python-version` says which Python to use (3.12 here). uv can download that Python if it is missing.
- `pyproject.toml` lists direct dependencies with a minimum version (`pydantic>=2.14.4`). `uv.lock` pins every version exactly, so a fresh clone gets the same packages.
- `[dependency-groups] dev` holds tools like pytest that the code itself does not need.

## Gotchas we hit

- **Commit `uv.lock`.** Without it, two machines can install different versions and get different results.
- **Use `uv add`, not `uv pip install`.** `uv pip install` puts a package in `.venv` but does not record it, so the next `uv sync` removes it again.
- **Packages that arrive by the back door.** `httpx` is installed because `langchain-openai` needs it, not because we asked for it. If we use it directly, it belongs in `pyproject.toml` too, so it does not vanish if that other package stops needing it.
- **pytest settings live in `pyproject.toml`.** `addopts = '-m "not live and not eval"'` is why plain `uv run pytest` skips the slow, paid tests.

## Further reading

- uv docs, projects: https://docs.astral.sh/uv/guides/projects/
- uv docs, locking and syncing: https://docs.astral.sh/uv/concepts/projects/sync/
