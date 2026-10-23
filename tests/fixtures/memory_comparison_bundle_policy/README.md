# Frozen evidence bundle policy contracts

Captured from unchanged production source at
`44ac164a8395c5847ae8792dded95d0dfe4526dd`, before extracting any policy.

`contract.json` records all original callable signatures, immutable DTO metadata,
and original-module pickle bytes. The 20 `case_*.json` files contain complete
ordered item payloads and diagnostics from representative baseline invocations.
They cover empty/unknown/missing roles, tied insertion order, all constructor
clamps, typed temporal support, partial event support, list coverage, required
role repair, source chains, complementary bridges, and noisy/diffuse provenance.
Equivalent clamped configurations share an expected output through
`config_variants`; they do not repeat the complete payload.

The capture also ran 468 existing planner/evidence/benchmark tests and recorded
251 unique planner invocations for independent pre/post replay outside the
repository. Capture asserted that every declared tuple candidate field was a
runtime tuple before JSON serialization. The tests restore these fields using
the dataclass annotations and retain the original list/tuple sequence arguments.

Expected outputs must not be regenerated merely because a refactor differs.
All values and source labels are synthetic existing test data.
