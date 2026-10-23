"""Pinned pre-source full-output and compatibility evidence for intent ownership."""

from __future__ import annotations

import base64
import dataclasses
import gzip
import hashlib
import importlib
import json
import pickle
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from infinity_context_server import memory_comparison_intent as legacy
from infinity_context_server.memory_comparison_rerank import query_retrieval_intent

from scripts.benchmark_policy_contract_inventory import binding_inventory

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/benchmark_retrieval_intent"


def _read(name):
    if name == "cases.json":
        raw = gzip.decompress((FIXTURES / "cases.json.gz").read_bytes())
        assert hashlib.sha256(raw).hexdigest() == _read("contract.json")["cases_sha256"]
        return json.loads(raw)
    return json.loads((FIXTURES / name).read_text())


def _json(value):
    return json.loads(json.dumps(value))


def replay(case, policy):
    """Replay the public policy boundary without the server's question-term machinery."""
    payload = dict(case["intent"])
    time_payload = payload["time_intent"]
    time = policy.RetrievalTimeIntent(
        time_payload["is_temporal"],
        tuple(time_payload["terms"]),
        tuple(time_payload["surface_terms"]),
        time_payload["kind"],
    )
    common = {
        "question": payload["question"],
        "relation_terms": tuple(payload["relation_terms"]),
        "time_intent": time,
        "visual_terms": tuple(payload["visual_terms"]),
        "multi_hop_markers": tuple(payload["multi_hop_markers"]),
    }
    relations = policy.infer_relation_intents(
        **common, relation_variant_terms=tuple(payload["relation_variant_terms"])
    )
    needs = policy.merge_relation_evidence_needs(
        policy.infer_evidence_need(
            **common,
            benchmark_category=case["category"],
            answer_unit_shapes=tuple(payload["answer_unit_shapes"]),
        ),
        relations,
    )
    entities = tuple(
        policy.RetrievalEntityIntent(
            value["canonical"], tuple(value["surfaces"]), tuple(value["speaker_surfaces"])
        )
        for value in payload["entities"]
    )
    values = {
        key: tuple(value) if isinstance(value, list) else value for key, value in payload.items()
    }
    values.update(
        {
            "entities": entities,
            "time_intent": time,
            "relation_intents": relations,
            "evidence_need": needs,
            "bundle_evidence_roles": policy.infer_bundle_evidence_roles(
                evidence_need=needs, benchmark_category=case["category"]
            ),
            "risk_flags": policy.infer_risk_flags(
                entity_count=len(entities),
                relation_terms=common["relation_terms"],
                relation_variant_terms=tuple(payload["relation_variant_terms"]),
                time_intent=time,
            ),
        }
    )
    result = policy.RetrievalIntent(**values)
    return _json(
        {
            "intent": dataclasses.asdict(result),
            "diagnostics": result.to_diagnostics(),
            "profile": result.to_query_profile(),
        }
    )


def test_frozen_consumer_and_direct_policy_outputs():
    for case in _read("cases.json"):
        expected = {key: case[key] for key in ("intent", "diagnostics", "profile")}
        assert replay(case, legacy) == expected
        result = query_retrieval_intent(
            SimpleNamespace(
                question=case["intent"]["question"], metadata={"category": case["category"]}
            )
        )
        assert _json(dataclasses.asdict(result)) == case["intent"]
        assert _json(result.to_diagnostics()) == case["diagnostics"]
        assert _json(result.to_query_profile()) == case["profile"]


def test_all_facets_roles_temporal_precedence_and_risks_are_frozen():
    contract = _read("contract.json")
    assert list(legacy._RELATION_FACET_CONFIG) == contract["facet_order"]
    assert set(contract["facet_order"]) <= set(contract["coverage"]["relation_categories"])
    for case in _read("roles.json"):
        inputs = dict(case["input"], evidence_need=tuple(case["input"]["evidence_need"]))
        assert list(legacy.infer_bundle_evidence_roles(**inputs)) == case["expected"]
    for case in _read("times.json"):
        inputs = {
            key: tuple(value) if isinstance(value, list) else value
            for key, value in case["input"].items()
        }
        assert legacy.infer_time_intent_kind(**inputs) == case["expected"]
    time = legacy.RetrievalTimeIntent(False, (), (), "none")
    for case in _read("risks.json"):
        inputs = {
            key: tuple(value) if isinstance(value, list) else value
            for key, value in case["input"].items()
        }
        assert list(legacy.infer_risk_flags(**inputs, time_intent=time)) == case["expected"]


def test_original_exports_signatures_annotations_and_executable_global_bindings():
    manifest = _read("ownership.json")
    assert binding_inventory(legacy, manifest["owners"]) == manifest["bindings"]
    # Before relocation these are original objects; afterward they must be canonical owner aliases.
    if legacy.RetrievalIntent.__module__ != legacy.__name__:
        for name, owner in manifest["owners"].items():
            assert getattr(legacy, name) is getattr(importlib.import_module(owner), name)
        policy = importlib.import_module("infinity_context_benchmarks.retrieval_intent")
        assert list(policy.__all__) == _read("contract.json")["public_names"]
        for case in _read("cases.json"):
            assert replay(case, policy) == {
                key: case[key] for key in ("intent", "diagnostics", "profile")
            }


def test_legacy_pickles_dataclass_identity_and_new_round_trips():
    contract = _read("contract.json")
    for name, encoded in contract["legacy_reference_pickles"].items():
        assert pickle.loads(base64.b64decode(encoded)) is getattr(legacy, name)
    for name, encoded in contract["legacy_pickles"].items():
        value = pickle.loads(base64.b64decode(encoded))
        assert type(value) is getattr(legacy, name)
        assert dataclasses.replace(value) == value
        assert pickle.loads(pickle.dumps(value)) == value
        assert get_type_hints(type(value))
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, dataclasses.fields(value)[0].name, None)


def test_duplicate_relation_merge_preserves_first_category_and_value_order():
    first = legacy.RetrievalRelationIntent("activity", ("read",), ("books",), "activity", ("a",))
    second = legacy.RetrievalRelationIntent("activity", ("paint", "read"), (), "other", ("b",))
    result = legacy._dedupe_relation_intents((first, second))
    assert result == (
        legacy.RetrievalRelationIntent(
            "activity", ("read", "paint"), ("books",), "activity", ("a", "b")
        ),
    )
