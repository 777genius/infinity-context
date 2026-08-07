# Mem0 OSS adapter v5

Provider-isolated adapter for the attested shared full-run benchmark lane. It exposes only four
authenticated mutation endpoints: admission, one-attempt dispatch, durable status readback, and
terminal cleanup. The adapter never accepts private source messages over HTTP. Dispatch resolves
each committed unit from the sealed read-only input manifest.

## Security boundary

- binds only to numeric loopback on the host;
- sends HTTP only to the dedicated immutable e904 transport origin
  `http://127.0.0.1:8891`, read from `MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE`;
- keeps the Phase C logical receipt route `http://127.0.0.1:8890/v1` unchanged and binds both
  route and transport digests into admission evidence;
- rejects unknown fields, type coercion, oversized bodies, redirects, and request hash mismatch;
- performs exactly one provider attempt during dispatch and none during status;
- stores only sanitized receipts and commitments;
- keeps the complete v4 adapter tree byte-exact.

`runtime-lock.json` pins dependencies only and is never a source trust root. Source authority is a
separate immutable Pin B manifest generated from the archived Pin A commit. The exact same Pin B
digest file is mandatory at build time through `MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE` and at
runtime through a dedicated read-only bind from that same source file; startup fails before runtime,
SQLite, Mem0, or Qdrant initialization when that external digest or closure is invalid.

Provider-free tests use an injected fake runtime. Docker builds and live calls are separate,
explicitly gated operations and are not part of the focused unit-test command.

The sealed input manifest file must be an absolute regular file with mode `0400`. Secret files
must be absolute regular files with mode `0600` or stricter and contain exactly one trimmed value.
The input directory is mounted read-only; the private state directory is the only writable bind.
The host must run the dedicated receipt-v2-capable immutable e904 runtime on port `8891`. Port
`8890` remains the canonical logical authority route and is never used as this adapter's HTTP
transport endpoint.

## Authentication key isolation

State authentication and durable-result/evidence authentication use distinct mandatory keys.
MEM0_V5_STATE_HMAC_FILE authenticates SQLite state only. MEM0_V5_RESULT_HMAC_FILE authenticates durable result artifacts and domain-separated storage/search evidence receipts. Startup fails closed when the two secret values are equal.
