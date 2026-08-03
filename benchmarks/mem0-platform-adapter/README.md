# Mem0 Platform benchmark adapter

This tracked adapter exposes the benchmark compatibility API while delegating storage to
managed Mem0 Platform. Runtime reports and state belong in the ignored `reports/` and `state/`
directories.

Bootstrap the exact SDK from a hash-verified local wheel so Python records PEP 610 install
evidence in `direct_url.json`:

```bash
./scripts/bootstrap.sh
./.venv/bin/uvicorn mem0_platform_adapter.app:app
```

`runtime-pin.json` binds the Mem0 SDK identity and the canonical SHA-256 plus artifact count of
`runtime-lock.json`. The compact lock freezes every runtime and test wheel for CPython 3.13/Linux
x86_64 with an exact PyPI URL and SHA-256. Before installation, bootstrap verifies every download,
reads each wheel's `Name`, `Version`, and `Requires-Dist` metadata, and proves the active marker-aware
dependency closure against the exact locked versions. It then installs with `--no-deps`, installs
the verified Mem0 wheel last, and requires `pip check` to pass. The deprecated `requirements.txt`
exists only for tooling compatibility.

Standalone `pytest` runs skip the external Infinity Context contract suite when its root package
is unavailable. Combined integration must use an explicit authoritative checkout and never copies
contract modules into this adapter:

```bash
INFINITY_CONTEXT_ROOT=/absolute/path/to/infinity-context \
  ./scripts/test-combined-contracts.sh
```

The combined runner fails before collection when required root modules are absent and makes root
import failures fatal with `MEM0_ADAPTER_REQUIRE_ROOT_CONTRACTS=1`.

Every file, including the generated lock, stays below the repository's 1000-line cap. Run the
lock consistency gate with `./.venv/bin/pytest tests/test_runtime_lock.py`.

Set `MEM0_API_KEY`, `MEM0_ADAPTER_INGRESS_API_KEY`, and
`MEM0_BENCHMARK_PROBE_TOKEN` only through the runtime's secret manager. Never reuse one value for
another purpose.

The HTTP authentication policy is intentionally split:

- `POST /memories`, `POST /search`, and `DELETE /memories` are the benchmark data plane. They
  require the exact `X-API-Key` value configured as `MEM0_ADAPTER_INGRESS_API_KEY`.
- A missing, blank, or whitespace-padded server ingress key fails closed with sanitized HTTP 503. A missing, wrong, or
  non-exact client key returns sanitized HTTP 401.
- `GET /health` and `GET /benchmark/capabilities` are public, read-only discovery endpoints. They
  expose neither ingress nor upstream credentials.
  Health reports `ingress_auth_configured=false` and never reports `ready=true` while the
  data-plane credential is absent.
- `POST /benchmark/auth-challenge` and `POST /benchmark/attest-timestamp` are control-plane probes.
  They continue to require only the separate `X-Benchmark-Probe-Token` value configured as
  `MEM0_BENCHMARK_PROBE_TOKEN`.
- Readback used to prove timestamp persistence and delete absence is internal to authenticated
  data-plane operations or the separately authenticated attestation refresh. No public readback
  route exists.

For example, a benchmark client sends:

```text
X-API-Key: <value supplied by the benchmark secret manager>
```

Capability responses never include keys, the local wheel URL, or filesystem paths.
