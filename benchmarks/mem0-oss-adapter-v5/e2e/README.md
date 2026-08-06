# Provider-free hosting E2E

This harness performs one real Mem0 v5 container admission and dispatch without a
provider or API key. The fake subscription runtime issues an authentic receipt-v2
with zero token usage. An outer process independently verifies the adapter's
authenticated SQLite state and the Qdrant/SQLite storage projection.

The stack requires two pre-existing immutable inputs:

- the final Pin B source-authority directory and its separately pinned SHA file;
- a separate byte-verified runtime-authority mirror owned and readable by the
  daemon-mapped host UID/GID. Do not reuse or mutate the primary authority copy.

The harness never modifies either authority.

## Run on hosting

These commands apply only to the inspected dedicated rootless daemon lane. Its
UID and GID maps are `0 -> 994/985` and `1..65536 -> 231072..296607`.
Consequently container UID/GID `65532:65532` maps to host UID/GID
`296603:296603` (`231072 + 65532 - 1`). Re-inspect the daemon child's
`/proc/<pid>/uid_map` and `gid_map` before using another lane; do not infer a
mapping from the SSH user.

The hosting operator must pre-provision both a private run parent and a separate
immutable e904 runtime-authority mirror for mapped host identity
`296603:296603`. This harness neither creates that mirror nor calls `chown`.
Prepare fails before writing unless its effective host UID/GID match the explicit
mapped IDs, while independently requiring the container identity to remain
`65532:65532`.

```bash
export HOST_MAPPED_UID=296603
export HOST_MAPPED_GID=296603
export CONTAINER_RUNTIME_UID=65532
export CONTAINER_RUNTIME_GID=65532
export RUN_PARENT="/absolute/private/host-296603-owned/hosting-volume-directory"
export RUN_ROOT="$RUN_PARENT/mem0-v5-e2e-$(date +%s)"
export UV_CACHE_DIR="$RUN_PARENT/uv-cache"
export TMPDIR="$RUN_PARENT/tmp"
/usr/bin/setpriv --reuid="$HOST_MAPPED_UID" --regid="$HOST_MAPPED_GID" --clear-groups \
  /usr/local/bin/uv run --frozen --no-sync python -m e2e.prepare \
  --run-root "$RUN_ROOT" \
  --host-mapped-uid "$HOST_MAPPED_UID" \
  --host-mapped-gid "$HOST_MAPPED_GID" \
  --container-runtime-uid "$CONTAINER_RUNTIME_UID" \
  --container-runtime-gid "$CONTAINER_RUNTIME_GID"
```

Export only paths, never secret values:

```bash
export MEM0_V5_INPUT_DIR="$RUN_ROOT/input"
export MEM0_V5_STATE_DIR="$RUN_ROOT/state"
export MEM0_V5_SECRET_DIR="$RUN_ROOT/secrets"
export MEM0_V5_FAKE_RUNTIME_STATE_DIR="$RUN_ROOT/fake-runtime"
export MEM0_V5_RUNTIME_AUTHORITY_DIR="/absolute/path/to/separate-verified-host-296603-mirror"
export MEM0_V5_SOURCE_AUTHORITY_DIR="/absolute/path/to/phase-c-authority"
export MEM0_V5_SOURCE_AUTHORITY_PIN_DIR="/absolute/path/to/final-pin-b"
export MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE="$MEM0_V5_SOURCE_AUTHORITY_PIN_DIR/manifest.sha256"
export DOCKER_HOST="unix:///run/infinity-locomo-docker/docker.sock"
```

Use a unique project name matching `mem0-v5-e2e-*`. The only Compose network is
an internal bridge with no default outbound route. Qdrant, fake-runtime, and the
adapter share the anchor's network namespace; its health gate proves both
dependencies ready before the adapter starts. The runner also waits for the
published adapter and Qdrant endpoints. Every Compose and lifecycle command is
pinned to the dedicated daemon socket below; the runner fails closed rather than
falling back to a rootful or user-default Docker socket.

```bash
DOCKER_HOST="$DOCKER_HOST" docker compose \
  -p "$PROJECT_NAME" -f compose.provider-free-e2e.yaml up -d --build \
  e2e-network-anchor mem0-oss-v5-qdrant mem0-oss-v5-fake-runtime
DOCKER_HOST="$DOCKER_HOST" docker compose \
  -p "$PROJECT_NAME" -f compose.provider-free-e2e.yaml up -d \
  mem0-oss-adapter-v5
DOCKER_HOST="$DOCKER_HOST" /usr/local/bin/uv run --frozen --no-sync python -m e2e.run \
  --run-root "$RUN_ROOT" \
  --runtime-authority-mirror "$MEM0_V5_RUNTIME_AUTHORITY_DIR" \
  --node /usr/local/bin/node \
  --compose-file "$PWD/compose.provider-free-e2e.yaml" \
  --project-name "$PROJECT_NAME"
```

The public result contains digests, a verdict, and the fake provider call count.
It contains no prompt, output, account identifier, bearer, or HMAC key.

Always remove only the exact unique compose project after the verdict:

```bash
DOCKER_HOST="$DOCKER_HOST" docker compose \
  -p "$PROJECT_NAME" -f compose.provider-free-e2e.yaml down --volumes
```
