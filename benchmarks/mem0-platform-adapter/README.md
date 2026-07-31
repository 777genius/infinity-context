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

Set `MEM0_API_KEY` only in the runtime environment. Capability responses never include the key,
the local wheel URL, or filesystem paths.
