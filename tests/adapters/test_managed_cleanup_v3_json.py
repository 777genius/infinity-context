from __future__ import annotations

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_json import strict_json_object
from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error


@pytest.mark.parametrize(
    "value",
    [
        '{"nested":{"value":1},"items":[true,null]}',
        {"nested": {"value": 1}, "items": [True, None]},
    ],
)
def test_strict_json_object_accepts_raw_asyncpg_text_and_mapping(value):
    assert strict_json_object(value, "strict_json_invalid") == {
        "nested": {"value": 1},
        "items": [True, None],
    }


@pytest.mark.parametrize(
    "value",
    [
        '{"duplicate":1,"duplicate":2}',
        '{"value":NaN}',
        '{"value":1e999}',
        '["not-an-object"]',
        {"tuple_is_not_json": (1, 2)},
        {1: "non-string-key"},
    ],
)
def test_strict_json_object_rejects_duplicate_nonfinite_and_type_drift(value):
    with pytest.raises(ManagedCleanupV3Error, match="strict_json_invalid"):
        strict_json_object(value, "strict_json_invalid")
