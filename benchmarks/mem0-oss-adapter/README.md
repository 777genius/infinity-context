# Mem0 OSS benchmark adapter

This is an isolated, ingress-protected Mem0 OSS compatibility adapter for benchmark use.
It uses canonical Qdrant storage, a pinned offline FastEmbed artifact, and an
explicit metadata timestamp because Mem0 OSS does not persist the SDK timestamp
argument. It does not modify the repository's platform adapter.

## Immutable runtime

- `mem0ai==2.0.15`, source `50bdaaea0c02744720ed374d88584fd01494eeb7`
- `fastembed==0.8.0`, public model `BAAI/bge-small-en-v1.5`, 384 dimensions
- FastEmbed's actual resolved artifact is pinned as
  `qdrant/bge-small-en-v1.5-onnx-q@52398278842ec682c6f32300af41344b1c0b0bb2`
  with `model_optimized.onnx` SHA-256
  `51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431`
- Qdrant `v1.18.3` and Python `3.11-slim` are locked by OCI digest.

`runtime-pin.json` and `runtime-lock.json` are the source of truth. The bootstrap
script downloads only those wheel URLs, verifies every wheel digest and METADATA
closure, then installs without dependency resolution.

## Modes and safety

The default `raw_passthrough` mode invokes `Memory.add(..., infer=False)`, so the
adapter permits zero extraction calls. `subscription_llm` is opt-in and accepts
only a loopback HTTP OpenAI-compatible bridge plus an explicit bearer token; it
uses `gpt-5.6-sol`, permits one extraction request per add, and records bounded
usage. Subscription extraction is an `isolated_single_add` smoke path: its
`user_id` / `run_id` must be fresh and empty, and a second add is rejected before
the model call. Ambient OpenAI and Mem0 provider variables are cleared before
SDK setup.

The additive v4 contract exposes signed usage evidence only for one exact,
isolated add. `POST /benchmark/attest-usage` requires both the dedicated ingress
key and probe token. It returns hashes plus a sanitized aggregate containing only
the extraction mode, operation/call counts, bounded byte counts, fixed model and
operation timestamps. Raw run identifiers, prompts, content, token counts,
bridge URLs and credentials are never returned.
The response-time `attested_at` value is bound into both the canonical usage
fingerprint and HMAC witness. Operation timestamps remain historical evidence;
only `attested_at` is suitable for freshness validation. Raw runs may aggregate
up to 10,000 adds while proving zero extraction; subscription evidence remains
one isolated add and one extraction call.

The runtime cache is staged during image build, verifies the actual FastEmbed
artifact, and forces Hugging Face and Transformers offline at runtime. Telemetry
is disabled.

Delete snapshots at most 10,000 exact Qdrant ids for one `user_id` / `run_id`,
then removes those vectors, Mem0 SQLite history, deterministic conversation
messages, and derived entity records. Any incomplete logical cleanup fails
closed. This is not a physical-media-erasure claim: Qdrant segment compaction
remains a server-controlled operation.

## Local deployment contract

Set dedicated values for `MEM0_ADAPTER_INGRESS_API_KEY` and
`MEM0_BENCHMARK_PROBE_TOKEN`, then use `compose.yaml` when an approved canary is
needed. `/benchmark/capabilities` is intentionally static and unbound. Only
`POST /benchmark/attest-timestamp` runs the isolated write/read/delete witness
and returns its paired HMAC refresh binding and witness.

For an approved disposable Linux/amd64 hosted canary, use
`compose.hosted-canary.yaml`. It uses host networking so an optional subscription
bridge remains loopback-only, binds the adapter to `127.0.0.1:8080`, binds Qdrant
to `127.0.0.1:6333`, and keeps adapter/Qdrant state in temporary memory-backed
filesystems. The compose file is a deployment contract only; it is not exercised
by unit tests.

No Docker build, Qdrant canary, or subscription bridge request was run while this
adapter was prepared. The hosted checks are static and mocked only.
