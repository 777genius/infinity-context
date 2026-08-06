from __future__ import annotations

from types import MappingProxyType

import pytest
from infinity_context_server.memory_comparison_response_format_policy import (
    locomo_judge_response_format,
    locomo_judge_response_format_policy,
    locomo_judge_response_format_policy_sha256,
    normalized_supported_response_format,
)


def test_locomo_judge_policy_returns_exact_fresh_strict_schema() -> None:
    expected = {
        "type": "json_schema",
        "json_schema": {
            "name": "locomo_judge",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string"},
                    "label": {"type": "string", "enum": ["CORRECT", "WRONG"]},
                },
                "required": ["reasoning", "label"],
                "additionalProperties": False,
            },
        },
    }
    first = locomo_judge_response_format()
    assert first == expected

    first["json_schema"]["schema"]["required"].clear()
    assert locomo_judge_response_format() == expected


def test_response_format_normalizer_preserves_legacy_and_rejects_drift() -> None:
    assert normalized_supported_response_format({"type": "json_object"}) == {
        "type": "json_object"
    }
    assert normalized_supported_response_format(
        MappingProxyType({"type": "json_object"})
    ) == {"type": "json_object"}
    with pytest.raises(ValueError, match="unsupported"):
        normalized_supported_response_format(
            {"type": "json_schema", "json_schema": {"strict": False}}
        )


def test_locomo_normalization_policy_has_exact_canonical_hashes() -> None:
    policy = locomo_judge_response_format_policy()

    assert policy == {
        "policy_id": "locomo-official-json-object-to-strict-schema.v1",
        "benchmark": "locomo",
        "stage": "judge",
        "source_response_format": {"type": "json_object"},
        "normalized_response_format": locomo_judge_response_format(),
        "canonical_schema_sha256": (
            "2461f7a465be82aa67751dc04e0717cde75c69b86e7db54bb306a2e3d1d4d8f0"
        ),
        "backend_roles": ["infinity-context", "mem0"],
        "backend_application": "identical",
    }
    assert locomo_judge_response_format_policy_sha256() == (
        "9d7bcc89f3e8cc3683a18d83d90d6ffde05cdb02358d1cd055bf273f92a772f1"
    )


@pytest.mark.parametrize(
    ("field", "impostor"),
    (("strict", 1), ("strict", 1.0), ("additionalProperties", 0), ("additionalProperties", 0.0)),
)
def test_response_format_comparison_rejects_bool_numeric_impostors(
    field: str,
    impostor: object,
) -> None:
    value = locomo_judge_response_format()
    if field == "strict":
        value["json_schema"][field] = impostor
    else:
        value["json_schema"]["schema"][field] = impostor

    with pytest.raises(ValueError, match="unsupported"):
        normalized_supported_response_format(value)


def test_response_format_comparison_rejects_nested_primitive_subclass() -> None:
    class StringImpostor(str):
        pass

    value = locomo_judge_response_format()
    value["json_schema"]["schema"]["properties"]["reasoning"]["type"] = StringImpostor(
        "string"
    )

    with pytest.raises(ValueError, match="unsupported values"):
        normalized_supported_response_format(value)
