# Docker Compose

## What it is

Docker runs a program in a container: a sealed box with the program and everything it needs, so it runs the same on any machine. Docker Compose starts several containers together, from one file, and wires them up so they can talk to each other.

Think of it as a flat-pack kit for a small office. `docker-compose.yml` is the instruction sheet: which rooms (services) to build, which doors connect them (the network), which door opens to the street (the published port) and where the filing cabinets go (volumes, which keep data when the office is closed).

## How we use it

We use it for one thing: running Langfuse locally ([docker-compose.yml](../../docker-compose.yml)). Langfuse is six services:

| Service | Job |
| --- | --- |
| `langfuse-web` | The website and API. The only one published to your machine, on `127.0.0.1:3000` |
| `langfuse-worker` | Takes queued trace events and writes them to ClickHouse |
| `postgres` | Users, projects, keys and settings |
| `clickhouse` | The traces themselves, built for fast counting and filtering |
| `redis` | The queue between web and worker |
| `minio` | File storage (S3-compatible) for raw events and media |

```bash
uv run python scripts/generate_secrets.py   # once: fill .env with random passwords
docker compose up -d                        # start everything in the background
docker compose ps                           # check that each service is "Up" or "healthy"
docker compose logs langfuse-web            # read one service's log
docker compose down                         # stop; data is kept in volumes
docker compose down -v                      # stop and delete all data
```

## What our file changes from the official one

- **No default passwords.** Every secret uses `${NAME:?message}`. If it is missing from `.env`, Compose stops with that message instead of starting with a weak default.
- **Only one port is published**, and only on `127.0.0.1`, so nothing is reachable from other machines on your network. The other services talk to each other by service name (`postgres`, `redis`) inside Docker's own network.
- **`depends_on` with `condition: service_healthy`** makes the web and worker wait until the databases pass their health checks, instead of crashing on start.
- **Telemetry is off** by default.

## Gotchas we hit

- **Memory.** Give Docker Desktop at least 4 GB, or ClickHouse can fail to start.
- **The first start is slow**, about 1 to 2 minutes, while images download and databases set themselves up.
- **`localhost` on Windows** can point at IPv6 `::1`, while the port is only published on IPv4. Use `http://127.0.0.1:3000` if the connection is refused.
- **`down -v` is permanent.** It deletes the volumes, so every trace, user and API key is gone.

## Further reading

- Docker Compose overview: https://docs.docker.com/compose/
- Langfuse self-hosting with Docker Compose: https://langfuse.com/self-hosting/deployment/docker-compose
