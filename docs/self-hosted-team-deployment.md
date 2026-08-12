# Self-hosted team deployment

Infinity Context supports a small-team self-hosted deployment where the API, projection
worker and extraction worker run as separate processes, while Postgres remains
the canonical source of truth.

## Shape

```text
Frontend / SDK / MCP clients
  -> infinity_context_server
    -> Postgres canonical storage
    -> local asset volume
    -> infinity_context_projection_worker
    -> infinity_context_extraction_worker
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

Generate a separate value for the service token and for each of the six
Postgres passwords. Do not reuse the admin password. The API and workers receive
only the least-privileged `infinity_context_runtime` connection; the admin
connection exists only in the short-lived identity and ACL bootstrap services.

Start the default small-team stack:

```bash
make infinity-context-selfhost-up
```

The make target validates that all seven secrets are non-placeholder and unique.
The identity bootstrap repeats the same fail-closed validation, so direct Compose
startup cannot bypass it.

On a fresh database Compose executes this fail-closed chain before serving
traffic:

```text
Postgres health
  -> identity bootstrap
  -> schema migrations
  -> runtime ACL reconciliation
  -> default seed
  -> API health
  -> projection and extraction workers
```

Every step must complete successfully. Compose will not start the API after a
failed identity, migration, ACL or seed step.

Check health:

```bash
curl -fsS http://127.0.0.1:${MEMORY_SERVER_PORT:-7788}/v1/health
```

Run the self-hosted smoke. It builds and starts the stack, uploads a text asset,
waits for the extraction worker, verifies extracted document chunks and then
stops the stack unless `--keep-stack` is passed:

```bash
make infinity-context-selfhost-smoke
```

Stop it:

```bash
docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml down
```

## Worker contract

The same worker binary supports explicit workload roles:

```bash
python -m infinity_context_server.worker --loop --role projection
python -m infinity_context_server.worker --loop --role extraction
python -m infinity_context_server.worker --loop --role all
```

`projection` processes derived index and auto-memory work. `extraction` only
processes `workload_class=extraction` jobs such as `asset.extract`. `all` keeps
the legacy behavior for tests, local debugging and emergency draining.

For extraction workers, `MEMORY_EXTRACTION_WORKER_LIMIT` controls the number of
claimed outbox jobs per poll. `MEMORY_EXTRACTION_WORKER_CONCURRENCY` controls
how many claimed extraction jobs run concurrently inside one process and
defaults to `1`; scale it only after parser/provider limits are sized for the
host.

Archive-like documents are inspected before parser/provider execution. Tune
these limits for extraction workers that accept DOCX/PPTX/XLSX/EPUB/ZIP inputs:

```text
MEMORY_EXTRACTION_MAX_ARCHIVE_ENTRIES=2000
MEMORY_EXTRACTION_MAX_ARCHIVE_UNCOMPRESSED_BYTES=262144000
MEMORY_EXTRACTION_MAX_ARCHIVE_COMPRESSION_RATIO=100
```

Path traversal, encrypted entries, excessive entry counts, excessive declared
uncompressed size and suspicious compression ratios are rejected as unsupported
extractions with bounded public diagnostics.

## Full provider profile

The default self-hosted stack keeps Qdrant, Graphiti and external embeddings
disabled. To run the full provider shape, set the relevant values in
`.env.selfhost`, including `MEMORY_OPENAI_API_KEY` or `OPENAI_API_KEY`, then run:

```bash
make infinity-context-selfhost-up-full
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

- Postgres volume: `infinity_context_postgres_data`
- asset and extraction artifact volume: `infinity_context_assets`

Derived data:

- Qdrant volume: `infinity_context_qdrant_data`
- Neo4j volume: `infinity_context_neo4j_data`

Back up Postgres and assets first. Qdrant and Neo4j are useful to snapshot for
fast recovery, but they must remain rebuildable from canonical Postgres rows and
asset/artifact blobs.

For team/hosted readiness diagnostics, configure storage governance explicitly:

```text
MEMORY_ASSET_STORAGE_BACKUP_POLICY_CONFIGURED=true
MEMORY_ASSET_STORAGE_OBJECT_LIFECYCLE_POLICY_CONFIGURED=true
MEMORY_ASSET_STORAGE_MAINTENANCE_ENABLED=true
```

These flags do not create backups or object lifecycle rules by themselves. They
tell `/v1/capabilities` and diagnostics that the operator has configured those
policies outside the app. Keep `MEMORY_ASSET_STORAGE_CLEANUP_APPLY_ENABLED=false`
until cleanup dry runs are reviewed.

`/v1/capabilities.storage.deployment_readiness` also reports schema management
readiness. In team/server deployments `MEMORY_AUTO_CREATE_SCHEMA=false` is the
expected mode, and the readiness payload will show:

```text
schema_management_mode=external_migration_runner
migration_runner_required=true
migration_runner_service=infinity_context_migrate
```

This means the API server is not responsible for creating or migrating schema at
startup. Run the migration service before serving traffic, then use
`/v1/capabilities` and the admin doctor command to confirm readiness.

Example Postgres dump:

```bash
docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml \
  exec -T infinity_context_postgres \
  pg_dump -U infinity_context_admin infinity_context > infinity-context-postgres.sql
```

### Upgrading an existing Postgres 16 volume

The self-hosted compose file pins PostgreSQL 18.4. PostgreSQL data directories
cannot be opened by a different major version, so Compose never attempts an
in-place automatic upgrade. Before changing an existing PostgreSQL 16 stack:

1. Keep the old image running and create a complete logical dump with `pg_dump`
   or `pg_dumpall`. Back up the asset volume separately.
2. Stop the stack without `-v`; retain the old named volume until restore has
   been verified.
3. Start PostgreSQL 18 with a new empty volume and the new distinct identity
   secrets.
4. Restore the dump with an administrative connection, then run the identity,
   migration and ACL bootstrap chain.
5. Verify API health, `/v1/capabilities`, row counts and a backup/restore drill
   before retiring the PostgreSQL 16 volume.

Do not point PostgreSQL 18 at the PostgreSQL 16 data directory. For large
deployments, use a separately planned `pg_upgrade` procedure with rollback and
storage headroom rather than adapting the Compose quick start.

## Production notes

- Put the API behind Caddy, Nginx, Traefik or a cloud load balancer with HTTPS.
- Do not expose Postgres, Qdrant or Neo4j directly to the internet.
- Never pass the admin database URL to the API or either worker.
- Rotate the five non-admin Postgres passwords as one coordinated maintenance
  operation. Drain API traffic and stop the API and workers first:

  ```bash
  docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml \
    stop infinity_context_server infinity_context_projection_worker \
    infinity_context_extraction_worker
  ```

  Keep the current admin password unchanged, replace all five non-admin values
  (`MIGRATOR`, `RUNTIME`, `CANONICAL`, `REGISTRAR` and `SEALER`) in
  `.env.selfhost`, then rotate them atomically through the supported CLI:

  ```bash
  docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml \
    run --rm --no-deps infinity_context_identity_bootstrap \
    python -m infinity_context_server.selfhost_db rotate-passwords
  docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml \
    run --rm --no-deps infinity_context_runtime_acl
  docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml \
    up -d --force-recreate infinity_context_server \
    infinity_context_projection_worker infinity_context_extraction_worker
  ```

  If the rotation command fails, keep dependent services stopped, restore the
  previous five values in `.env.selfhost`, and investigate before restarting.
  Do not rotate these connected identities independently while services run.
- `python -m infinity_context_server.selfhost_db rotate-passwords` does not
  rotate the bootstrap admin. Changing `POSTGRES_PASSWORD` or
  `INFINITY_CONTEXT_SELFHOST_ADMIN_PASSWORD` in the env file also does not
  change the admin password in an existing Postgres volume. Rotate the admin in
  a separate DBA maintenance procedure using the current admin connection or a
  trusted local Postgres socket (prefer `psql`'s `\\password` command so the new
  value is not stored in shell history), then update the admin value in
  `.env.selfhost` before the next bootstrap operation.
- Rotate `MEMORY_SERVICE_TOKEN` when a team member or automation loses access.
- Keep `MEMORY_AUTO_CREATE_SCHEMA=false` in server mode; migrations run through
  the `infinity_context_migrate` service.
- Scale extraction separately by increasing `infinity_context_extraction_worker`
  replicas or moving it to a larger host.
