# Provider-free hosting E2E

This harness performs one real Mem0 v5 container admission and dispatch without
a provider or API key. The fake subscription runtime issues an authentic
receipt-v2 with zero token usage. Independent auditors verify authenticated
SQLite state and the Qdrant/SQLite projection.

The stack has no published or exposed ports. Qdrant, fake-runtime, and adapter
share one passive anchor's internal-only network namespace. The host runner
attests the dedicated rootless Docker daemon, the exact Compose anchor and its
network, opens only `/proc/<pid>/ns/net`, closes the replacement race, and runs
the fixed `e2e.run` module through pinned `/usr/bin/nsenter`.

## Immutable inputs

Provision these outside the harness:

- final source-authority directory owned by `root:root`, mode `0555`, with
  `manifest.json` and canonical 64-byte `manifest.sha256` owned by `root:root`,
  mode `0444` and link count one;
- fixed Node authority directory and executable owned by `root:root`, mode
  `0555`, on a root-owned path chain with no group/other write access;
- byte-verified runtime-authority mirror owned by mapped host UID/GID
  `296603:296603` and readable as container UID/GID `65532:65532`.

The harness never mutates either authority. Re-inspect a different daemon's UID
and GID maps instead of copying these identities to another lane.

## Exact hosting flow

Prepare a fresh private run root as the mapped host identity. Use a task-specific
`MEM0_DIR`; do not change `HOME`. Increment `RUN_SEQUENCE` for every attempt and
keep `SOURCE_PIN_HEX` equal to the basename of the reviewed final authority.

```bash
cd /mnt/volume_ams3_1784742570542/infinity-context/worktrees/mem0-oss-adapter-v5-r1/benchmarks/mem0-oss-adapter-v5
export HOST_MAPPED_UID=296603
export HOST_MAPPED_GID=296603
export CONTAINER_RUNTIME_UID=65532
export CONTAINER_RUNTIME_GID=65532
export SOURCE_PIN_HEX="ccd75535"
export RUN_SEQUENCE="r7"
export PROJECT_NAME="mem0-v5-e2e-${SOURCE_PIN_HEX}-${RUN_SEQUENCE}"
export RUN_PARENT="/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark/e2e-runs/host296603"
export RUN_ROOT="$RUN_PARENT/$PROJECT_NAME"
export HOST_PYTHON="$RUN_PARENT/e2e-venv/bin/python"
export UV_CACHE_DIR="$RUN_PARENT/uv-cache"
export TMPDIR="$RUN_PARENT/tmp"
export MEM0_DIR="$RUN_PARENT/mem0-config"
/usr/bin/setpriv --reuid="$HOST_MAPPED_UID" --regid="$HOST_MAPPED_GID" --clear-groups \
  "$HOST_PYTHON" -m e2e.prepare \
  --run-root "$RUN_ROOT" \
  --host-mapped-uid "$HOST_MAPPED_UID" \
  --host-mapped-gid "$HOST_MAPPED_GID" \
  --container-runtime-uid "$CONTAINER_RUNTIME_UID" \
  --container-runtime-gid "$CONTAINER_RUNTIME_GID"
```

Export paths only, never secret values:

```bash
export MEM0_V5_INPUT_DIR="$RUN_ROOT/input"
export MEM0_V5_STATE_DIR="$RUN_ROOT/state"
export MEM0_V5_SECRET_DIR="$RUN_ROOT/secrets"
export MEM0_V5_FAKE_RUNTIME_STATE_DIR="$RUN_ROOT/fake-runtime"
export MEM0_V5_RUNTIME_AUTHORITY_DIR="/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark/e2e-runtime-authorities/e904ec95-uid65532-host296603"
export MEM0_V5_SOURCE_AUTHORITY_DIR="/mnt/volume_ams3_1784742570542/infinity-context/sources/9499b9c2"
export MEM0_V5_SOURCE_AUTHORITY_PIN_DIR="/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark/e2e-source-authorities/$SOURCE_PIN_HEX"
export MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE="$MEM0_V5_SOURCE_AUTHORITY_PIN_DIR/manifest.sha256"
export MEM0_V5_NODE_EXECUTABLE_SOURCE="/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark/e2e-runtime-authorities/node-b2959781/node"
export DOCKER_HOST="unix:///run/infinity-locomo-docker/docker.sock"
export COMPOSE_FILE="$PWD/compose.provider-free-e2e.yaml"
```

Install cleanup before creating any project resources. Cleanup targets only the
exact unique Compose project.

```bash
cleanup() {
  DOCKER_HOST="$DOCKER_HOST" /usr/bin/docker compose \
    -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down --volumes
}
trap cleanup EXIT INT TERM

DOCKER_HOST="$DOCKER_HOST" /usr/bin/docker compose \
  -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d --build \
  e2e-network-anchor mem0-oss-v5-qdrant mem0-oss-v5-fake-runtime
DOCKER_HOST="$DOCKER_HOST" /usr/bin/docker compose \
  -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d mem0-oss-adapter-v5

DOCKER_HOST="$DOCKER_HOST" /usr/bin/python3.12 -I -S "$PWD/e2e/namespace_runner.py" \
  --run-root "$RUN_ROOT" \
  --runtime-authority-mirror "$MEM0_V5_RUNTIME_AUTHORITY_DIR" \
  --node "$MEM0_V5_NODE_EXECUTABLE_SOURCE" \
  --compose-file "$COMPOSE_FILE" \
  --project-name "$PROJECT_NAME" \
  --host-python "$HOST_PYTHON"
```

Run the namespace runner as root. It requires the exact dedicated socket,
root-owned immutable `/usr/bin/docker`, `/usr/bin/nsenter`, and `/usr/bin/setpriv`,
and treats daemon UID `994` as an explicit trusted boundary. Before every Docker
CLI call it revalidates the socket, pidfile, dockerd process, UID/GID maps, and
data/exec roots. The child runs only after dropping to mapped UID/GID
`296603:296603` with supplementary groups cleared, all capability sets cleared,
and `no_new_privs`. The child cannot traverse or open the Docker socket. Its one
fixed restart request crosses a private inherited socketpair to the root wrapper,
which alone runs the two exact Docker lifecycle commands. Its environment is an explicit path-only
allowlist. The public result contains only the exact canonical PASS verdict;
child stderr and Docker inspection failures are sanitized.
