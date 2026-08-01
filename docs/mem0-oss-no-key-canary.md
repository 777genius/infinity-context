# Mem0 OSS No-Key Canary

This runbook is the exact engineering path for comparing Infinity Context with
local Mem0 OSS without `MEM0_API_KEY` or an OpenAI API key. It does not make a
Mem0 Platform run keyless.

## Choose the right lane

| Lane | Real Mem0 backend | `MEM0_API_KEY` | Extraction / embedding | Answer / judge | What it proves |
| --- | --- | --- | --- | --- | --- |
| Offline or mock tests | No | Not used | Fakes or fixtures | Deterministic | Local code and report contracts only |
| Local Mem0 OSS canary | Yes, self-hosted and auth-disabled | Must be unset | Local Ollama | Authenticated Codex CLI session | OSS HTTP ingest/search plus the comparison pipeline |
| Hosted Mem0 Platform | Yes, `api.mem0.ai` | Required | Platform-managed | Provider-specific | Platform behavior |

An authenticated Codex CLI session replaces only the benchmark answerer and
judge API credentials. It does not authenticate Mem0 Platform and it does not
provide Mem0 OSS extraction or embeddings.

## Frozen inputs

Use a disposable checkout outside this repository. This repository does not
contain a checked-in Compose definition for the no-key stack.

- `memory-benchmarks` revision:
  `4b61c5d31b9c668a12b4f5e78064248a02c82d2b`
- `mem0ai==2.0.14`
- `ollama==0.6.2` (Python client installed in the Mem0 wrapper image)
- `qdrant-client==1.18.0`
- `ollama/ollama:0.32.3`
- `qdrant/qdrant:v1.18.3`
- Ollama extraction model: `llama3.1`
- Ollama embedding model: `nomic-embed-text` (768 dimensions)
- audited LoCoMo file SHA-256:
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`

Primary sources:

- [Frozen memory-benchmarks revision](https://github.com/mem0ai/memory-benchmarks/tree/4b61c5d31b9c668a12b4f5e78064248a02c82d2b)
- [Frozen upstream Ollama configuration](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/configs/ollama.yaml)
- [Frozen Mem0 OSS wrapper](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/docker/mem0/main.py)
- [Mem0 OSS configuration documentation](https://docs.mem0.ai/open-source/configure)
- [mem0ai 2.0.14 package](https://pypi.org/project/mem0ai/2.0.14/)
- [Ollama v0.32.3 release](https://github.com/ollama/ollama/releases/tag/v0.32.3)
- [qdrant-client 1.18.0 package](https://pypi.org/project/qdrant-client/1.18.0/)
- [Qdrant v1.18.3 release](https://github.com/qdrant/qdrant/releases/tag/v1.18.3)
- [LoCoMo dataset source](https://github.com/snap-research/locomo/blob/main/data/locomo10.json)

Clone and verify the external harness:

```sh
git clone https://github.com/mem0ai/memory-benchmarks.git /path/to/memory-benchmarks-no-key
git -C /path/to/memory-benchmarks-no-key checkout --detach 4b61c5d31b9c668a12b4f5e78064248a02c82d2b
test "$(git -C /path/to/memory-benchmarks-no-key rev-parse HEAD)" = \
  4b61c5d31b9c668a12b4f5e78064248a02c82d2b
```

The frozen upstream wrapper depends on a moving Mem0 Git branch. In this
disposable checkout only, replace that direct-URL requirement with the three
audited pins before building:

```diff
-mem0ai @ git+https://github.com/mem0ai/mem0.git@feat/v3-pipeline
+mem0ai==2.0.14
+ollama==0.6.2
+qdrant-client==1.18.0
```

Do not commit this overlay to either repository. Build the wrapper from the
frozen external checkout:

```sh
cd /path/to/memory-benchmarks-no-key
docker build --no-cache \
  -t mem0-oss-no-key:mb-4b61c5d31b9 \
  ./docker/mem0

docker run --rm mem0-oss-no-key:mb-4b61c5d31b9 \
  python -c 'from importlib.metadata import version; print(version("mem0ai"), version("ollama"), version("qdrant-client"))'
```

The version check must print `2.0.14 0.6.2 1.18.0`.

Stage `locomo10.json` from the primary LoCoMo source or an already audited
local copy. Do not let a benchmark command silently download it. Verify it:

```sh
test "$(sha256sum /path/to/locomo10.json | awk '{print $1}')" = \
  79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4
```

On macOS, use `shasum -a 256 /path/to/locomo10.json` instead of `sha256sum`.

## Exact local model and vector configuration

Save the following as `mem0-config.no-key.yaml` in the disposable
`memory-benchmarks` checkout:

```yaml
version: "v1.1"

llm:
  provider: ollama
  config:
    model: llama3.1
    ollama_base_url: http://ollama:11434
    temperature: 0.1

embedder:
  provider: ollama
  config:
    model: nomic-embed-text
    ollama_base_url: http://ollama:11434
    embedding_dims: 768

vector_store:
  provider: qdrant
  config:
    host: qdrant
    port: 6333
    collection_name: mem0_no_key_canary_v1
    embedding_model_dims: 768

history_db_path: /app/history/history.db
```

On Docker Desktop, Ollama may run natively on the host instead of inside the
8 GiB Docker VM. In that lane, replace both `http://ollama:11434` values with
`http://host.docker.internal:11434`, run `ollama pull llama3.1` and
`ollama pull nomic-embed-text` on the host, and omit the Ollama container,
network alias and Ollama volume below. Qdrant and the Mem0 wrapper remain
isolated in Docker.

Start the isolated services. Bind HTTP ports to loopback because the frozen
wrapper deliberately has no ingress authentication:

```sh
docker network create mem0-no-key-canary
docker volume create mem0-no-key-ollama
docker volume create mem0-no-key-qdrant
docker volume create mem0-no-key-history

docker run -d --name mem0-no-key-ollama \
  --network mem0-no-key-canary --network-alias ollama \
  -p 127.0.0.1:11434:11434 \
  -v mem0-no-key-ollama:/root/.ollama \
  ollama/ollama:0.32.3

docker exec mem0-no-key-ollama ollama pull llama3.1
docker exec mem0-no-key-ollama ollama pull nomic-embed-text

docker run -d --name mem0-no-key-qdrant \
  --network mem0-no-key-canary --network-alias qdrant \
  -p 127.0.0.1:6333:6333 \
  -v mem0-no-key-qdrant:/qdrant/storage \
  qdrant/qdrant:v1.18.3

docker run -d --name mem0-no-key-api \
  --network mem0-no-key-canary \
  -p 127.0.0.1:8888:8000 \
  -e MEM0_TELEMETRY=false \
  -e QDRANT_HOST=qdrant \
  -e QDRANT_PORT=6333 \
  -e COLLECTION_NAME=mem0_no_key_canary_v1 \
  -v "$PWD/mem0-config.no-key.yaml:/app/config.yaml:ro" \
  -v mem0-no-key-history:/app/history \
  mem0-oss-no-key:mb-4b61c5d31b9
```

Do not pass `OPENAI_API_KEY`, `MEMORY_OPENAI_API_KEY`, `MEM0_API_KEY`, Azure,
Anthropic or AWS credentials to these containers. The explicit YAML prevents
Mem0 from falling back to its OpenAI defaults. Keep `MEM0_TELEMETRY=false` so
the isolated canary does not send anonymous usage events to PostHog.

## Service and CLI preflight

First check only local service metadata, not inference:

```sh
curl --fail --silent http://127.0.0.1:11434/api/tags >/dev/null
curl --fail --silent http://127.0.0.1:6333/healthz >/dev/null
curl --fail --silent http://127.0.0.1:8888/health >/dev/null
curl --fail --silent http://127.0.0.1:8888/openapi.json >/dev/null
codex login status
```

Start the Infinity Context comparison API separately on loopback at port 7788,
using a fresh sandbox/test project only. `MEMORY_SERVICE_TOKEN` below is the
local Infinity Context service token; it is unrelated to `MEM0_API_KEY`.

From the Infinity Context repository root, run the sanitized preflight. Keep
all key and managed-Platform markers explicitly removed from the child process:

```sh
env \
  -u MEM0_API_KEY \
  -u MEM0_BENCHMARK_PROBE_TOKEN \
  -u MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT \
  -u MEMORY_OPENAI_API_KEY \
  -u OPENAI_API_KEY \
  -u AZURE_OPENAI_API_KEY \
  -u ANTHROPIC_API_KEY \
  MEMORY_SERVICE_TOKEN=local-dev-token \
  python -m infinity_context_server.eval memory-comparison-benchmark \
    --dataset /path/to/locomo10.json \
    --memo-api-url http://127.0.0.1:7788 \
    --mem0-url http://127.0.0.1:8888 \
    --mem0-api-key-env MEM0_API_KEY \
    --benchmark locomo \
    --locomo-ingest-mode official-turns \
    --max-cases 8 \
    --top-k 200 \
    --top-k-cutoff 200 \
    --answerer-provider codex \
    --judge-provider codex \
    --answerer-model gpt-5.5 \
    --judge-model gpt-5.5 \
    --codex-command codex \
    --codex-timeout-seconds 180 \
    --report-mode compact \
    --allow-live \
    --preflight-only \
    --preflight-probe-services
```

Required result: `ok=true`, `safe_to_run_live=true`, both service probes pass,
the dataset is readable, and Codex mode is selected. The
`mem0_api_key_configured` warning is intentional for this lane. Because this is
an 8-case canary rather than the `locomo-fast` quality gate,
`ready_for_locomo_fast=false` and its fast-readiness blockers are also expected.
Any other required or service-probe failure is a stop condition.

## Bounded 8-case canary

Only after preflight passes, run:

```sh
env \
  -u MEM0_API_KEY \
  -u MEM0_BENCHMARK_PROBE_TOKEN \
  -u MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT \
  -u MEMORY_OPENAI_API_KEY \
  -u OPENAI_API_KEY \
  -u AZURE_OPENAI_API_KEY \
  -u ANTHROPIC_API_KEY \
  MEMORY_SERVICE_TOKEN=local-dev-token \
  python -m infinity_context_server.eval memory-comparison-benchmark \
    --dataset /path/to/locomo10.json \
    --memo-api-url http://127.0.0.1:7788 \
    --mem0-url http://127.0.0.1:8888 \
    --mem0-api-key-env MEM0_API_KEY \
    --benchmark locomo \
    --locomo-ingest-mode official-turns \
    --max-cases 8 \
    --top-k 200 \
    --top-k-cutoff 200 \
    --answerer-provider codex \
    --judge-provider codex \
    --answerer-model gpt-5.5 \
    --judge-model gpt-5.5 \
    --codex-command codex \
    --codex-timeout-seconds 180 \
    --report-mode compact \
    --runtime-timeout-seconds 7200 \
    --allow-live \
    --run-id locomo-oss-no-key-canary-001 \
    --report-out .e2e-artifacts/memory-comparison-locomo-oss-no-key-canary.json
```

One cutoff is deliberate. The call budget is:

```text
8 cases x 2 backends x (1 answer + 1 judge) = 32 Codex CLI calls
```

Adding the usual four cutoffs would raise that to 128 Codex calls. Do not add
cutoffs or increase `--max-cases` until this bounded canary is healthy. Use a
new `--run-id` for every attempt; the default reset then deletes only that
isolated Mem0 user/run before ingest. Do not pass `--mem0-skip-reset` for this
auth-disabled wrapper.

## Resource floor and worker NO-GO

Run this on a dedicated host with, at minimum, 4 CPU cores, 16 GiB of actually
available RAM at startup, and 25 GiB of free disk. More headroom is recommended
for CPU-only `llama3.1` inference. Check available memory and disk immediately
before starting containers, not just the machine's nominal totals.

🚨 Do not run this local-model canary on a shared Codex worker or on any worker
already under memory, swap or disk pressure. The audited worker had only about
4.8 GiB RAM available and 20 GiB disk free on a 96% full filesystem, so it is a
NO-GO even though its nominal RAM was 15 GiB. Use a dedicated sandbox host; do
not reclaim space or stop unrelated workloads on a shared worker to force the
run through.

## What can and cannot be published

This result may be retained as an internal engineering canary proving that the
keyless OSS HTTP pipeline works. It is not publishable as an authoritative
Mem0 Platform comparison or a general quality ranking because:

- the target is the auth-disabled OSS wrapper, not Mem0 Platform `/v3`;
- only eight cases are selected;
- Codex `gpt-5.5` is not the same answerer/judge setup as all upstream tables;
- `llama3.1` plus `nomic-embed-text` differs from upstream published OSS runs
  that used other extraction and embedding stacks;
- Codex CLI usage is estimated locally and subscription cost is not measured;
- latency depends on the local CPU/GPU and is not cross-host comparable;
- Ollama model tags and Docker tags are not immutable content digests, and the
  upstream Dockerfile's `python:3.12-slim` base plus remaining Python
  dependencies are not fully locked.

Before publishing any reproducibility claim, capture image digests, Ollama
model digests, the complete Python lock, hardware, dataset hash, repository
commits, sanitized runtime manifest, and the full report. For a Platform claim,
use an account-issued `MEM0_API_KEY` and the Platform-specific runner instead.
