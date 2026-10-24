# Demand-loaded core compatibility exports

## Recovery provenance

This implementation is a reconstruction after the execution filesystem reset. Its actual
production/test commit is `e4a13e058fea649ad5141c103423541d3f1baf09`, based on published
`9b119f3b80c784f04316dc97382980e55fbb2198`. It is not claimed to be byte-identical to lost
local source commit `fb3ddf73` or its lost documentation commit `89732dc8`. The twice-reviewed
plan remains the approved design; the reconstructed bytes require fresh implementation reviews.

The published before-source contract fixture survived unchanged. Its SHA-256 is
`4cab9f5b3568b4b3d50b4810fb39317c73519fd00fcc97bb0e2d744b5bebc675`.
The fixture records the original capture base `ab834d55a3e6123655a8db974559228ccc8b107b`
and both original initializer source hashes. Before reconstruction, the restored initializers
were checked against those recorded hashes. Neither fixture nor capture generator was changed.

## Change and ownership

Root/application package imports previously initialized legacy use cases and four feature public
surfaces before a caller could import a domain or port module. They now initialize only standard
library mechanics, one shared technical resolver and an ordered static compatibility manifest.
Attribute access resolves the existing object through its original public import route and caches
that object in the package namespace. Feature aliases continue through `public` modules,
preserving ADR-0007 ownership.

All 31 root exports and 267 application exports retain exact advertised order and list type,
original object identity, signatures, evaluated hints, class/function reference pickles,
module-valued feature aliases and cross-package aliases. Representative domain, DTO and error
instance pickles remain valid. `dir` advertises names before materialization; explicit imports and
star imports preserve the full surface and ordering. Unknown attributes keep the original
conventional `AttributeError`. Real import errors propagate unchanged, and failed resolutions
are not cached.

Static type discovery is retained in explicit `TYPE_CHECKING` imports and bundle assignments.
The static route test compares every advertised typing route with the unchanged fixture,
including the benchmark constant's short typing alias. The runtime resolver contains no business
policy, provider dependency, auto-discovery, proxy object, dynamic module forwarding or mutable
service registry. No class, use-case, DTO or port implementation changed.

Production sizes in the reconstructed tree:

| File | Lines |
| --- | ---: |
| Root initializer | 161 |
| Application initializer | 807 |
| Ordered application manifest | 363 |
| Shared technical resolver | 23 |
| Technical namespace initializer | 1 |

All five files remain below the hard cap. No legacy budget exception or ADR change is required.
The initializer layout differs from the lost tree because the reconstructed typing imports use
explicit self aliases; runtime contracts are verified against the preserved original evidence.

## Executed reconstruction gates

Using the frozen Python 3.12 environment, standard repository pytest configuration, unset
`PYTHONPATH`, disabled bytecode and pytest cache, and bounded owned temporary directories:

- **373 passed:** complete frozen contracts; fresh-interpreter closure, caching, import forms
  and real-error checks; exact static typing routes/runtime-import guards; core/feature/cognitive
  architecture boundaries; domain fact behavior; existing context policy snapshots.
- **20 passed:** focused fact API and legacy/context HTTP composition, ingest/deduplication/
  deletion and public keyword recall under actual process execution.
- Changed-file Ruff and `git diff --check` passed.
- File-size boundaries against published `9b119f3b` passed with all 101 frozen legacy ceilings.

The 320-test compatibility/fresh-process suite is included in the 373-test gate; these counts
are not additive. The 20 API/composition tests are a separate gate. The initial reconstruction
check exposed an incomplete DTO test inventory; the corrected inventory follows the actual
unchanged DTO aggregate imports and their existing public feature contracts. No expected export
metadata or production fixture was regenerated to obtain a passing result.

Fresh interpreters use `-I` and only this worktree's explicit core package path. Every loaded core
module must resolve inside that path. Bare root initialization loads exactly three technical
modules; bare application initialization adds only its package and static manifest. Domain,
ports, feature domain and safety imports are checked against complete allowed dependency roots.
The DTO aggregate retains its existing memory-facts/review-governance public feature contracts;
its complete closure excludes other legacy application use cases, ranking, packing and collectors.
Introspection does not materialize exports, and first access caches the exact defining object
after one resolver call. These are dependency and identity assertions, not timing benchmarks.

## Acceptance status

Both fresh independent implementation reviewers approved reconstructed source
`e4a13e058fea649ad5141c103423541d3f1baf09` without a blocking finding or required source fix:

- [E2E critic](reviews/review-code-core-b-recovered-by-e2e.md): independently checked the
  unchanged fixture SHA, original initializer AST, all 31/267 ordered routes and compatibility
  mechanics; the focused 320-test gate passed in 5.60 seconds.
- [Architecture critic](reviews/review-code-core-b-reconstructed-by-architecture.md):
  independently checked the unchanged fixture and original source hashes, all 298 runtime and
  static routes, public feature/benchmark aliases and dependency closures; the focused
  320-test gate passed in 5.92 seconds.

These independently repeated 320-test results overlap each other and the owner's 373-test
suite. They are not additional unique cases to sum. Previous approvals apply to the lost tree;
these new reports explicitly approve the reconstructed bytes. No production source changed
after either fresh review.
Root owns final combined-tree units, offline evaluations, installed-wheel checks, E2E,
publication and merge acceptance. No paid/live provider calls were used.
