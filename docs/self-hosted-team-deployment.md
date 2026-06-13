# Self-hosted team deployment

Memo Stack supports a small-team self-hosted deployment where the API, projection
worker and extraction worker run as separate processes, while Postgres remains
the canonical source of truth.

## Shape

```text
Frontend / SDK / MCP clients
  -> memo_stack_server
    -> Postgres canonical storage
    -> local asset volume
    -> memo_stack_projection_worker
    -> memo_stack_extraction_worker
    -> optional Qdrant / Neo4j projections
```

The deployment is a modular monolith: the services share one codebase and one
database contract, but the heavy extraction workload is isolated into its own
worker process so it can be scaled, paused or resource-limited independently.

## Quick start

Create a local env file and replace every `change-me` value:

```bash
cp .env.selfhost.example .env.selfhost
openssl rand -hex 32
```

Start the default small-team stack:

```bash
docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml up -d --build
```

Check health:

```bash
curl -fsS http://127.0.0.1:${MEMORY_SERVER_PORT:-7788}/v1/health
```

Run the self-hosted smoke. It builds and starts the stack, uploads a text asset,
waits for the extraction worker, verifies extracted document chunks and then
stops the stack unless `--keep-stack` is passed:

```bash
make memo-stack-selfhost-smoke
```

Stop it:

```bash
docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml down
```

## Worker contract

The same worker binary supports explicit workload roles:

```bash
python -m memo_stack_server.worker --loop --role projection
python -m memo_stack_server.worker --loop --role extraction
python -m memo_stack_server.worker --loop --role all
```

`projection` processes derived index and auto-memory work. `extraction` only
processes `workload_class=extraction` jobs such as `asset.extract`. `all` keeps
the legacy behavior for tests, local debugging and emergency draining.

## Full provider profile

The default self-hosted stack keeps Qdrant, Graphiti and external embeddings
disabled. To run the full provider shape, set the relevant values in
`.env.selfhost`, including `MEMORY_OPENAI_API_KEY` or `OPENAI_API_KEY`, then run:

```bash
docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml --profile full up -d --build
```

Minimum full-mode flags:

```text
MEMORY_QDRANT_ENABLED=true
MEMORY_EMBEDDINGS_ENABLED=true
MEMORY_EMBEDDINGS_PROVIDER=openai
MEMORY_GRAPHITI_ENABLED=true
MEMORY_GRAPHITI_BUILD_INDICES=true
```

For a fully private self-hosted deployment, add a local embeddings adapter before
enabling vector search. The current full profile uses the OpenAI embeddings
adapter.

## Persistence and backup

Canonical data:

- Postgres volume: `memo_stack_postgres_data`
- asset and extraction artifact volume: `memo_stack_assets`

Derived data:

- Qdrant volume: `memo_stack_qdrant_data`
- Neo4j volume: `memo_stack_neo4j_data`

Back up Postgres and assets first. Qdrant and Neo4j are useful to snapshot for
fast recovery, but they must remain rebuildable from canonical Postgres rows and
asset/artifact blobs.

Example Postgres dump:

```bash
docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml \
  exec -T memo_stack_postgres \
  pg_dump -U memo_stack memo_stack > memo-stack-postgres.sql
```

## Production notes

- Put the API behind Caddy, Nginx, Traefik or a cloud load balancer with HTTPS.
- Do not expose Postgres, Qdrant or Neo4j directly to the internet.
- Rotate `MEMORY_SERVICE_TOKEN` when a team member or automation loses access.
- Keep `MEMORY_AUTO_CREATE_SCHEMA=false` in server mode; migrations run through
  the `memo_stack_migrate` service.
- Scale extraction separately by increasing `memo_stack_extraction_worker`
  replicas or moving it to a larger host.
