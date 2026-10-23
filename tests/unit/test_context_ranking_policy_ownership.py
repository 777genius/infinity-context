"""Replay full outputs frozen on the pre-consolidation production implementation."""

from __future__ import annotations

import base64
import dataclasses
import gzip
import hashlib
import inspect
import json
import pickle
from typing import get_type_hints

import pytest
from context_ranking_contract_support import BASE_SHA, FIXTURES, decode, encode, resolve

CASE_BYTES = (FIXTURES / "cases.json.gz").read_bytes()
CASES = json.loads(gzip.decompress(CASE_BYTES))
CONTRACT = json.loads((FIXTURES / "contracts.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[f"case_{i:04d}" for i in range(len(CASES))])
def test_complete_ranking_output_matches_unchanged_source(case):
    args, kwargs = decode(case["input"])
    result = resolve(case["module"], case["function"])(*args, **kwargs)
    assert encode(result) == case["output"], case["test"]
    if "same_argument" in case:
        assert (result is args[0]) is case["same_argument"], case["test"]
    if "same_members" in case:
        assert [
            [index for index, old in enumerate(args[0]) if item is old] for item in result
        ] == case["same_members"], case["test"]


def test_contract_is_pinned_to_original_production():
    assert CONTRACT["base_sha"] == BASE_SHA
    assert len(CASES) == CONTRACT["cases"]["count"] == 670
    assert hashlib.sha256(CASE_BYTES).hexdigest() == CONTRACT["cases"]["sha256"]
    assert (
        hashlib.sha256(gzip.decompress(CASE_BYTES)).hexdigest()
        == (CONTRACT["cases"]["uncompressed_sha256"])
    )
    assert len(CONTRACT["source_sha256"]) == 12


@pytest.mark.parametrize("name", tuple(CONTRACT["definitions"]))
def test_original_callable_references_and_annotations_resolve(name):
    original = CONTRACT["definitions"][name]
    current = resolve("infinity_context_core.application.context_ranking", name)
    assert pickle.loads(base64.b64decode(original["pickle"])) is current
    assert current.__name__ in (
        {name, "RequirementCoverageSignals"} if name == "_RequirementCoverageSignals" else {name}
    )
    assert inspect.getdoc(current) == original["doc"]
    # Evaluating real annotations catches missing relocated dependencies.
    assert get_type_hints(current)


@pytest.mark.parametrize(
    "name",
    tuple(
        name for name, contract in CONTRACT["definitions"].items() if "instance_pickle" in contract
    ),
)
def test_original_private_dto_instances_decode_through_aliases(name):
    contract = CONTRACT["definitions"][name]
    current = resolve("infinity_context_core.application.context_ranking", name)
    instance = pickle.loads(base64.b64decode(contract["instance_pickle"]))
    assert type(instance) is current
    assert [field.name for field in dataclasses.fields(current)] == contract["fields"]
    assert (
        encode(
            {field.name: getattr(instance, field.name) for field in dataclasses.fields(instance)}
        )
        == contract["instance_fields"]
    )
