# Mem0 v5 live micro-canary

This lane makes exactly one live subscription-runtime extraction call. It is not
a LoCoMo/LongMemEval run and imports no benchmark answerer, judge, or readiness
pipeline. Qdrant search, status, storage evidence, sealing, and cleanup are
provider-free.

## Safety contract

- input is exactly one case, one corpus, and one projected unit;
- the coordinator's normal plan budget remains 5, while the durable dispatch
  journal permits at most one extraction dispatch;
- an ambiguous dispatch is recovered in a fresh composition through status
  readback and `seal_restored_completed()`, never through another dispatch;
- GO requires at least one authenticated stored record and a nonempty
  authenticated scoped search result;
- every started lifecycle ends with authenticated terminal cleanup;
- reports contain token counts and commitments, but redact account/runtime
  release names and never include credentials or exception text;
- `requested_output_tokens=4096` is reported with `enforced=false`; the receipt
  proves what was requested, not provider-side enforcement.

## Prepare the one-unit input

Create a private directory with mode `0700`. The immutable case JSON must have
mode `0400` and exactly these top-level keys:

```json
{
  "case_id": "live-one-unit-001",
  "corpus_id": "locomo-corpus-<stable-id>",
  "record": {"schema_version": "memory-comparison-managed-corpus.v2"},
  "search_query": "A question answerable from the supplied memory"
}
```

Run the projector with the adapter's pinned Python environment because request
projection depends on the adapter-pinned Mem0 2.0.15 prompt implementation:

```sh
benchmarks/mem0-oss-adapter-v5/.venv/bin/python \
  scripts/mem0_v5_live_project_one_unit.py \
  --case-file /absolute/private/case.json \
  --case-sha256 <sha256> \
  --current-date 2026-08-07 \
  --input-root /absolute/private/input
```

This writes immutable `manifest.json` and `one-unit-authority.json`. Record their
SHA-256 digests before starting containers.

## Cached-image stack

Use
`benchmarks/mem0-oss-adapter-v5/compose.live-micro-canary.override.yaml` only
with locally cached exact `sha256:<64 hex>` image IDs. The override has no build
or pull path. A one-shot init service runs from the same exact cached adapter
image before Qdrant and the adapter. Readiness is TCP-only and never probes a
provider HTTP route.

The adapter port is fixed at `19091` and Qdrant at `6334`, matching the pinned
adapter runtime. All input, state, Qdrant, secret, runtime, source-authority, and
Node paths must be explicit absolute paths. Secret files remain mode `0600` in a
private host-runner `0700` directory; do not place secret values in command-line
arguments.

Never mount the host-runner input or secret directory into the UID 65532 adapter.
Create five distinct empty destinations: container input, container secrets,
adapter state, Qdrant state, and a public copy-authority directory. The init
service runs as container root with only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`,
copies the exact manifest and nine fixed adapter secrets, re-reads and compares
every SHA-256 digest, then makes the private copies and writable state owned by
UID/GID 65532 with modes `0700`, `0400`, and `0600`. Qdrant and the adapter start
only after init exits successfully.

The host secret root contains these adapter files at mode `0600`:
`account-binding-hmac-sha256`, `base-instructions-sha256`, `ingress-bearer`,
`result-hmac`, `runtime-attestation-secret`, `runtime-bearer`,
`runtime-receipt-secret`, `runtime-transport-origin`, and `state-hmac`. Runner-only
`checkpoint-signing-key` and `checkpoint-head-key` stay in the host secret root
and are never copied into the adapter. Before init, provision
`runtime-attestation-secret` as fresh random UTF-8 text between 32 and 4096 bytes
(for example, 32 random bytes encoded as 64 lowercase hexadecimal characters),
distinct from every other credential, with no surrounding whitespace. The init
service copies those exact bytes for the adapter; pass the host file to the runner
with `--runtime-attestation-secret-file`. If rootless ownership mapping or
`chown` cannot produce exact UID/GID 65532, init fails and the canary remains
NO-GO; do not relax host privacy or file modes.

## Preflight and live run

Invoke `scripts/mem0_v5_live_micro_canary.py` first with all required immutable
digests, image IDs, ports, credential file paths, private roots, Phase C package
root, runtime repository, its sibling `artifact-manifest.json`, Node executable,
the reviewed extraction-contract file and its exact SHA-256 digest,
the public evidence-key commitment (`sha256(result-hmac)`), and the immutable
`container-copy-authority.json` path/digest emitted by init, plus
`--preflight-only`. The artifact manifest path
must be exactly `<runtime-repo parent>/artifact-manifest.json`, which is also the
path consumed by `NodePublicReceiptVerifier`. Preflight does only local
validation, one-unit reprojection, digest comparison, and TCP readiness. The
production composition's reusable public trust preflight validates the exact
case/request/boundary/runtime/observed-receipt/dispatch-guard tuple before any
credential file is opened and before TCP readiness can produce GO. Only after
that succeeds are host secrets validated and compared with the init copy
authority. Preflight never calls the provider.

The reviewed Node executable SHA-256 is
`b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.
The runner rejects every other digest before opening credential files.

The runner and adapter use the same ingress bearer, receipt secret, runtime
attestation secret, and evidence material. In the adapter secret directory the
evidence material is named `result-hmac`; runner arguments point
`--evidence-key-file` to that host file and pass its public digest as
`--evidence-key-sha256`. Adapter SQLite
state HMAC and runner checkpoint signing/head keys remain distinct.

The immutable runtime authority uses schema
`managed-mem0-v5-live-runtime-authority.v3`. Its Phase C runtime response-format
and schema commitments are distinct from the adapter extraction response-format
and schema commitments. The runner binds Phase C receipt/runtime evidence to the
runtime pair and binds one-unit projection plus observed extraction receipts to
the extraction pair. Missing, legacy, swapped, or equalized pairs are NO-GO
before credentials, readiness, or provider access.

Run the same command without `--preflight-only` only after the report says GO.
Use a new private state root, dispatch journal, adapter state root, Qdrant state
root, and report filename for a new attempt. If a checkpoint exists, the runner
enters restore/status mode and never dispatches. A dispatch journal without its
checkpoint is an orphaned claim and is an immediate NO-GO.

Expected GO evidence includes:

- `hard_dispatch_guard_max=1` and `coordinator_full_plan_total_calls=5`;
- `extraction_calls=1` with exact prompt, completion, and total tokens;
- admission, manifest, operation, seal, authenticated search, and terminal
  cleanup commitments;
- at least one authenticated record and search result;
- terminal state `deleted`.

Do not run a full benchmark from this lane. Promote to a larger comparison only
after this one-unit report is reviewed and its terminal cleanup is verified.
