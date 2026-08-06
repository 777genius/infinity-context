# Phase C canary v5 foundation

This package is the provider-free control plane for a publishable Phase C canary.
It does not contain subscription credentials and cannot make a live call from its
offline CLI mode.

Its fixed authority binds Infinity Context source `9499b9c2`, immutable
subscription runtime `e904ec95`, public receipt schema v2, provider usage schema
v3, the `stateless-completion` profile, and strict JSON Schema responses. The
preflight verifies source/runtime manifests before any orchestration.

The provider ledger distinguishes `reserved`, `dispatched`, `committed`, and
`outcome_unknown`. A crash after dispatch is quarantined and is never retried
automatically because exactly-once network delivery cannot be proven without a
provider idempotency contract.

Readiness calibration and factual canary are separate phases. There is no exact
readiness-token baseline. Historical value 8063 may be used only as an optional
conservative ceiling, never as an expected token count.

Run provider-free checks from the immutable hosting worktree:

```sh
python -B -m pytest -q
ruff check .
python -B -m phase_c_canary.cli --mode offline --journal /path/on-large-volume/offline.sqlite3
```

Published evidence is authoritative only after the complete directory and its
self-hashing manifest are durably renamed on one filesystem. Reproduction bundles
must include the runner and scan identities, runtime manifests, pinned Python
closure, container identities, authority contract, and usage journal.

`live_enabled` remains false. This foundation does not provide a provider/live
adapter, notification gate, consistent SQLite evidence snapshot, runtime bundle
assembler, or SIGTERM wait/escalation policy. Those gaps must be closed and
reviewed before any factual canary can be called live-ready.

Child Python execution is derived only from the attested `venv/bin/python` and
uses `-B -P -S`. The complete venv regular-file, symlink, type, and directory
inventory is verified before launch. `-S` prevents declared or injected `.pth`
and `sitecustomize.py` startup execution; the single attested site-packages path
and four immutable Infinity package roots are supplied explicitly through the
strict child environment.
