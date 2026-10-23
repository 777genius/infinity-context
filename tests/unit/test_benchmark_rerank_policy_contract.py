"""Immutable complete score/contribution/consumer and legacy ownership contracts."""

from __future__ import annotations

import ast
import base64
import dataclasses
import gzip
import hashlib
import importlib
import importlib.util
import json
import pickle
from pathlib import Path
from types import SimpleNamespace

from infinity_context_server import memory_comparison_rerank_policies as policies
from infinity_context_server import memory_comparison_rerank_policy as score
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_rerank import benchmark_rerank_memories

from scripts.benchmark_policy_contract_inventory import (
    binding_inventory,
    replay_scoring_case,
    scoring_features,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/benchmark_rerank_policy"
PREFIX = "infinity_context_benchmarks.rerank_policy"


def _read(name):
    if name in {"cases.json", "activation_cases.json"}:
        raw = gzip.decompress((FIXTURES / (name + ".gz")).read_bytes())
        key = "cases_sha256" if name == "cases.json" else "activation_cases_sha256"
        assert hashlib.sha256(raw).hexdigest() == _read("contract.json")[key]
        return json.loads(raw)
    return json.loads((FIXTURES / name).read_text())


def _normalized(value):
    return json.loads(json.dumps(value))


def _api():
    return SimpleNamespace(
        BenchmarkRerankFeatures=score.BenchmarkRerankFeatures,
        score_benchmark_rerank_candidate=score.score_benchmark_rerank_candidate,
        score_rerank_policy_contributions=policies.score_rerank_policy_contributions,
    )


def test_complete_frozen_scores_contributions_and_signal_order():
    api = _api()
    cases = _read("cases.json")
    assert len(cases) == _read("contract.json")["case_count"]
    for case in cases:
        assert replay_scoring_case(case, api) == case["expected"]
    activation = _read("activation_cases.json")
    assert len(activation) == _read("contract.json")["activation_case_count"]
    for case in activation:
        assert replay_scoring_case(case, api) == case["expected"]
    active = {
        item["policy"]
        for case in [*cases, *activation]
        for item in case["expected"]["plan"]["contributions"]
        if item["score"] != 0 or item["reason_codes"]
    }
    assert active == set(_read("contract.json")["default_order"])
    if importlib.util.find_spec(PREFIX):
        canonical = importlib.import_module(PREFIX)
        for case in [*cases, *activation]:
            assert replay_scoring_case(case, canonical) == case["expected"]


def test_actual_rerank_consumer_retains_ties_memory_fields_and_full_metadata():
    for case in _read("consumers.json"):
        memories = tuple(
            RetrievedMemory(**dict(item, source_refs=tuple(item["source_refs"])))
            for item in case["input"]
        )
        actual, metadata = benchmark_rerank_memories(
            SimpleNamespace(question=case["question"], metadata={"category": 4}), memories
        )
        assert (
            _normalized(
                {"memories": [dataclasses.asdict(item) for item in actual], "metadata": metadata}
            )
            == case["expected"]
        )


def test_all_fifteen_individual_policies_default_order_and_structural_features():
    contract = _read("contract.json")
    features = scoring_features(contract["single_policy_input"], _api())
    assert [policy.name for policy in policies._DEFAULT_POLICIES] == contract["default_order"]
    for name, expected in contract["single_policy_plans"].items():
        plan = policies.score_rerank_policy_contributions(
            features, policies=(getattr(policies, name)(),)
        )
        assert _normalized(plan.to_diagnostics()) == expected
    default = policies.score_rerank_policy_contributions(features)
    assert policies.score_rerank_policy_contributions(features, policies=[]) == default
    structural = SimpleNamespace(**dataclasses.asdict(features))
    assert policies.score_rerank_policy_contributions(structural) == default


def test_custom_policy_order_and_duplicate_signal_overwrite_contract():
    class FixedPolicy:
        def __init__(self, name, value):
            self.name, self.value = name, value

        def score(self, _features):
            return policies.RerankPolicyContribution(
                self.name, self.value, {"same": self.name}, (self.name,)
            )

    features = scoring_features(_read("cases.json")[0]["input"], _api())
    plan = policies.score_rerank_policy_contributions(
        features, policies=(FixedPolicy("first", 0.1234567), FixedPolicy("second", 0.2))
    )
    assert [item.policy for item in plan.contributions] == ["first", "second"]
    assert plan.score_signals == {"same": "second"}
    assert plan.total_score == 0.323457


def test_supported_names_signatures_annotations_and_actual_execution_bindings():
    manifest, contract = _read("ownership.json"), _read("contract.json")
    for module in (score, policies):
        actual = binding_inventory(module, manifest["owners"], contract["public_names"])
        expected = manifest["bindings"][module.__name__]
        if score.BenchmarkRerankFeatures.__module__.startswith(PREFIX):
            for name in contract["typed_delegates"] if module is score else ():
                target = getattr(module, name)
                owner = manifest["owners"][policies.__name__ + "." + name]
                shared = getattr(importlib.import_module(owner), name)
                assert target.__globals__["_shared" + name] is shared
                # The typed delegate intentionally replaces only the arithmetic-body binding.
                actual[name]["callable"]["globals"] = expected[name]["callable"]["globals"]
        assert actual == expected


def test_legacy_class_function_and_instance_pickles_and_canonical_aliases():
    contract, manifest = _read("contract.json"), _read("ownership.json")
    for qualified, encoded in contract["legacy_reference_pickles"].items():
        module, name = qualified.rsplit(".", 1)
        assert pickle.loads(base64.b64decode(encoded)) is getattr(
            importlib.import_module(module), name
        )
    for name, encoded in contract["legacy_pickles"].items():
        value = pickle.loads(base64.b64decode(encoded))
        owner = score if hasattr(score, name) else policies
        assert type(value) is getattr(owner, name)
        assert dataclasses.replace(value) == value
        assert pickle.loads(pickle.dumps(value)) == value
    if score.BenchmarkRerankFeatures.__module__.startswith(PREFIX):
        canonical = importlib.import_module(PREFIX)
        assert list(canonical.__all__) == contract["public_names"]
        for qualified, owner in manifest["owners"].items():
            module, name = qualified.rsplit(".", 1)
            assert getattr(importlib.import_module(module), name) is getattr(
                importlib.import_module(owner), name
            )


def test_original_definitions_and_duplicate_arithmetic_have_one_canonical_body():
    if not score.BenchmarkRerankFeatures.__module__.startswith(PREFIX):
        return  # Capture test must also pass against untouched original production.
    contract, manifest = _read("contract.json"), _read("ownership.json")
    for qualified, expected in manifest["definitions"].items():
        module, name = qualified.rsplit(".", 1)
        if module == score.__name__ and name in contract["typed_delegates"]:
            owner = importlib.import_module(manifest["owners"][qualified])
            node = next(
                node
                for node in ast.parse(Path(owner.__file__).read_text()).body
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            assert len(node.body) == 1 and isinstance(node.body[0], ast.Return)
            call = node.body[0].value
            assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            assert call.func.id == "_shared" + name and not call.keywords
            assert len(call.args) == 1 and isinstance(call.args[0], ast.Name)
            assert call.args[0].id == "features"
            continue
        owner = importlib.import_module(manifest["owners"][qualified])
        definitions = []
        for node in ast.parse(Path(owner.__file__).read_text()).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
                definitions.append(node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                    definitions.append(node)
        assert len(definitions) == 1, qualified
        assert (
            hashlib.sha256(ast.dump(definitions[0], include_attributes=False).encode()).hexdigest()
            == expected
        ), qualified
    assert score._rounded_boosts is policies._rounded_boosts
    for proof in contract["helper_equivalence"].values():
        assert proof["concrete_contract"]["globals"] == proof["structural_contract"]["globals"]
