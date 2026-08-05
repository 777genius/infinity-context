# ADR-0008: Monotonic File-Size Budgets

Status: accepted

## Context

New code must remain reviewable, but 111 tracked source files already exceed the 1000-line
architecture limit. A permissive allowlist or a higher global ceiling lets legacy debt grow and
cannot distinguish a one-line regression from an intentional split.

## Decision

All tracked and prospective tracked `*.py`, `*.js`, `*.ts`, `*.tsx`, `*.rs`, and `*.dart` files
under `packages`, `scripts`, `tests`, and `frontend` have a 1000-line ceiling. Generated output,
caches, dependency trees, coverage output, and build artifacts are excluded.

`tests/architecture/file_size_legacy_baseline.json` freezes each existing oversized file at its
exact line count. These are ceilings, not exemptions:

- a legacy file may never grow above its ceiling, even by one line;
- when it shrinks but remains oversized, its ceiling must be lowered in the same change;
- when it reaches 1000 lines, its baseline entry must be removed;
- deleted, stale, malformed, newly added, or increased entries fail;
- no new source file may exceed 1000 lines.

The pull-request gate compares the proposed baseline with the PR base ref, and the push gate compares
it with the previous push commit. Once this ADR lands, new entries and increases are mechanically
prohibited; the comparison baseline is absent only for this initial bootstrap. Manual workflow
dispatches run the exact current-tree check without a base ref. Ceilings may only decrease.

Policy and diagnostics live in one dependency-free checker. Tests and automation call that checker
rather than duplicating globs or allowlists.

## Commands

```bash
make infinity-context-file-size-boundaries
FILE_SIZE_BASE_REF=origin/main make infinity-context-file-size-boundaries
make infinity-context-lint
```

## Consequences

Splits can proceed incrementally without demanding an immediate rewrite of every legacy file.
Any touched oversized file must either keep its exact size or ratchet downward, making debt movement
explicit and reviewable.
