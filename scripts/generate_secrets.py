"""Fill .env with random secrets for the local Langfuse server.

- If .env does not exist, it is created from .env.example.
- Every value that is still the placeholder "change-me" is replaced with a
  random hex string from Python's `secrets` module (made for passwords and keys).
- Values you have already set are left alone, so running it twice is safe.
- Secret values are never printed, only their names.

Hex is used because it has no characters like @ : / that would break the
Postgres connection URL or the Redis command line.

Run:  uv run python scripts/generate_secrets.py
"""

import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
PLACEHOLDER = "change-me"

# Name -> number of random bytes. Each byte becomes 2 hex characters.
SECRETS = {
    "POSTGRES_PASSWORD": 24,
    "CLICKHOUSE_PASSWORD": 24,
    "REDIS_AUTH": 24,
    "MINIO_ROOT_PASSWORD": 24,
    "SALT": 32,
    "ENCRYPTION_KEY": 32,  # Langfuse requires exactly 64 hex characters
    "NEXTAUTH_SECRET": 32,
}


def main() -> None:
    if not ENV.exists():
        shutil.copy(EXAMPLE, ENV)
        print("Created .env from .env.example")

    lines = ENV.read_text(encoding="utf-8").splitlines()
    filled, kept = [], []
    for i, line in enumerate(lines):
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and name in SECRETS:
            if value.strip() in ("", PLACEHOLDER):
                lines[i] = f"{name}={secrets.token_hex(SECRETS[name])}"
                filled.append(name)
            else:
                kept.append(name)

    missing = [n for n in SECRETS if n not in filled and n not in kept]
    for name in missing:  # .env was older than .env.example
        lines.append(f"{name}={secrets.token_hex(SECRETS[name])}")
        filled.append(name)

    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Generated: {', '.join(filled) or 'none'}")
    print(f"Already set, left alone: {', '.join(kept) or 'none'}")


if __name__ == "__main__":
    main()
