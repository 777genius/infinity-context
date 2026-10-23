"""Capture unchanged benchmark scoring bodies/contracts and complete output vectors."""

from __future__ import annotations

import argparse
import ast
import base64
import copy
import dataclasses
import gzip
import hashlib
import importlib
import json
import pickle
import subprocess
from pathlib import Path
from types import SimpleNamespace

from benchmark_policy_contract_inventory import binding_inventory, callable_record, scoring_features

SERVER = "infinity_context_server."
PREFIX = "infinity_context_benchmarks.rerank_policy."
SCORE = SERVER + "memory_comparison_rerank_policy"
POLICIES = SERVER + "memory_comparison_rerank_policies"
TYPED_DELEGATES = (
    "_relation_boost",
    "_relation_coverage_boost",
    "_focused_relation_density_boost",
    "_stale_only_current_state_evidence",
)
GROUPS = {
    "contracts": {
        "RerankPolicyFeatures",
        "RerankPolicyContribution",
        "RerankPolicyPlan",
        "RerankPolicy",
        "BenchmarkRerankFeatures",
        "BenchmarkRerankScore",
    },
    "common": {
        "_has_measured_locality_below",
        "_has_precise_or_unmeasured_source_provenance",
        "_has_positive_boost",
        "_rounded_boosts",
        "_reason_codes",
        "_has_missing_required_answer_evidence",
        "_MISSING_REQUIRED_ANSWER_EVIDENCE_REASONS",
    },
    "evidence": {
        "EntitySpeakerPolicy",
        "RelationCoveragePolicy",
        "FocusedTurnPolicy",
        "EvidenceBundlePolicy",
        "SourceGroundingPolicy",
        "_relation_boost",
        "_relation_coverage_boost",
        "_relation_category_coverage_boost",
        "_focused_relation_density_boost",
        "_speaker_grounding_eligible",
        "_visual_evidence_grounded",
        "_source_grounding_evidence_grounded",
        "_source_grounding_plausible_but_ungrounded",
        "_direct_speaker_relation_grounded",
    },
    "temporal": {
        "TemporalPolicy",
        "_typed_temporal_boost",
        "_temporal_sequence_direction",
        "_temporal_sequence_query_direction",
        "_temporal_sequence_direction_conflict",
        "_temporal_role_support_eligible",
        "_has_content_temporal_evidence",
        "_stale_only_current_state_evidence",
        "_has_temporal_query_role",
    },
    "intent": {
        "PreferenceIntentPolicy",
        "MultiHopPolicy",
        "ContrastIntentPolicy",
        "NegativeAbsencePolicy",
        "LocationIntentPolicy",
        "_preference_evidence_grounded",
        "_preference_reason_required",
        "_preference_reason_grounded",
        "_has_typed_preference_relation_hit",
        "_contrast_boost_eligible",
        "_negative_absence_evidence_grounded",
        "_PREFERENCE_POLARITY_TERMS",
        "_LOCATION_SUPPORT_TERMS",
    },
    "answer_shapes": {
        "AnswerabilityPolicy",
        "ValueAnswerShapePolicy",
        "CountListAnswerShapePolicy",
        "_has_count_list_subject_grounding",
        "_answerability_boost",
        "_answerability_boost_eligible",
        "_typed_category_answerability_grounded",
        "_COUNT_LIST_GENERIC_RELATION_TERMS",
    },
    "typed_relations": {
        "TypedRelationSupportPolicy",
        "_TYPED_RELATION_SUPPORT_ROLE_CATEGORIES",
        "_TYPED_RELATION_SUPPORT_NEEDS",
        "_TYPED_PROFILE_SUPPORT_CATEGORIES",
        "_typed_relation_support_roles",
        "_typed_relation_support_category_hits",
        "_typed_relation_support_hit_roles",
        "_typed_relation_support_grounded",
        "_support_goal_category_grounded",
        "_typed_profile_category_grounded",
    },
}


def definitions(source):
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            result[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            result[target.id] = node
    return result


def normalized(value):
    return json.loads(json.dumps(value))


def original_sources(base_sha):
    sources = {}
    nodes = {}
    for module in (SCORE, POLICIES):
        path = Path("packages/infinity_context_server/infinity_context_server") / (
            module.rsplit(".", 1)[-1] + ".py"
        )
        raw = subprocess.check_output(["git", "show", f"{base_sha}:{path}"])
        assert path.read_bytes() == raw, "Refuse oracle capture from changed production"
        sources[module] = hashlib.sha256(raw).hexdigest()
        nodes[module] = definitions(raw.decode())
    return sources, nodes


def capture(base_sha, output):
    assert not output.exists(), "Never overwrite immutable scoring expectations"
    sources, nodes = original_sources(base_sha)
    owners = {}
    for module, members in nodes.items():
        for name in members:
            owner = next((key for key, values in GROUPS.items() if name in values), "scoring")
            if module == SCORE and name in TYPED_DELEGATES:
                owner = "scoring"
            owners[f"{module}.{name}"] = PREFIX + owner
    score = importlib.import_module(SCORE)
    policies = importlib.import_module(POLICIES)
    public = [
        name
        for name, value in vars(policies).items()
        if isinstance(value, type) and value.__module__ == POLICIES
    ]
    public += [
        "BenchmarkRerankFeatures",
        "BenchmarkRerankScore",
        "score_rerank_policy_contributions",
        "score_benchmark_rerank_candidate",
    ]
    cases = {}
    original = score.score_benchmark_rerank_candidate

    def record(features):
        result = original(features)
        plan = policies.score_rerank_policy_contributions(features)
        inputs = dataclasses.asdict(features)
        cases[json.dumps(inputs)] = {
            "input": inputs,
            "expected": normalized(
                {
                    "score": dataclasses.asdict(result),
                    "plan": plan.to_diagnostics(),
                    "signals": plan.score_signals,
                }
            ),
        }
        return result

    score.score_benchmark_rerank_candidate = record
    import pytest

    try:
        status = pytest.main(
            [
                "-q",
                "--capture=sys",
                "-p",
                "no:cacheprovider",
                "tests/unit/test_memory_comparison_rerank_policy.py",
                "tests/unit/test_memory_comparison_source_grounding_rerank.py",
                "tests/unit/test_memory_comparison_evidence.py",
            ]
        )
        assert status == 0, status
    finally:
        score.score_benchmark_rerank_candidate = original
    base = {
        "overlap_terms": (),
        "entity_hits": (),
        "speaker_hits": (),
        "relation_hits": (),
        "relation_terms": (),
        "query_has_entities": True,
        "high_signal_relation_hit_count": 0,
        "is_temporal_query": False,
        "has_temporal_surface": False,
        "has_sequence_surface": False,
        "is_preference_query": False,
        "has_preference_evidence": False,
        "has_visual_terms": False,
        "has_visual_evidence": False,
        "focused_turn_boost": 0.0,
        "has_multi_hop_markers": False,
    }
    grounded = dict(
        base,
        overlap_terms=("alex", "project", "deadline"),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        relation_hits=("project", "deadline", "before"),
        relation_terms=("project", "deadline"),
        direct_speaker_turn=True,
        source_ref_count=1,
        answerability_score=0.7,
    )
    variants = {
        "source_locality_score": (-1.0, 0.0, 0.449999, 0.45, 0.649999, 0.65, 1.0),
        "answerability_score": (0.0, 0.149999, 0.15, 0.349999, 0.35, 0.5, 0.65, 1.0),
        "relation_category_coverage_ratio": (0.0, 0.499999, 0.5, 0.999999, 1.0),
        "high_signal_relation_hit_count": (0, 1, 2, 3),
        "list_item_count": (0, 1, 2, 3),
        "time_intent_kind": ("", "duration", "temporal_sequence", "relative_time", "explicit_time"),
        "temporal_sequence_direction": ("", "before", "after", "both"),
        "policy_boosts": ({}, {"a": 0.0000004}, {"a": 0.0000006}, {"b": 0.02, "a": 0.01}),
        "shape_boosts": ({}, {"a": 0.035}, {"a": -0.01}),
    }
    for field in dataclasses.fields(score.BenchmarkRerankFeatures):
        if field.type == "bool":
            variants[field.name] = (False, True)
    for values in (base, grounded):
        record(score.BenchmarkRerankFeatures(**values))
        for name, candidates in variants.items():
            for value in candidates:
                record(score.BenchmarkRerankFeatures(**dict(values, **{name: value})))
    sample = score.BenchmarkRerankFeatures(**grounded)
    single = {
        policy.name: normalized(
            policies.score_rerank_policy_contributions(sample, policies=(policy,)).to_diagnostics()
        )
        for policy in policies._DEFAULT_POLICIES
    }
    samples = {
        "BenchmarkRerankFeatures": sample,
        "BenchmarkRerankScore": original(sample),
        "RerankPolicyContribution": policies._DEFAULT_POLICIES[0].score(sample),
        "RerankPolicyPlan": policies.score_rerank_policy_contributions(sample),
    }
    equivalence = {}
    for name in (*TYPED_DELEGATES, "_rounded_boosts"):
        concrete = copy.deepcopy(nodes[SCORE][name])
        structural = copy.deepcopy(nodes[POLICIES][name])
        for definition in (concrete, structural):
            for parameter in definition.args.args:
                parameter.annotation = None
        assert ast.dump(concrete, include_attributes=False) == ast.dump(
            structural, include_attributes=False
        ), name
        left = callable_record(getattr(score, name), owners)
        right = callable_record(getattr(policies, name), owners)
        assert left["globals"] == right["globals"], name
        equivalence[name] = {
            "arithmetic_body_sha256": hashlib.sha256(
                ast.dump(concrete, include_attributes=False).encode()
            ).hexdigest(),
            "concrete_contract": left,
            "structural_contract": right,
            "compatibility": "typed-delegate" if name in TYPED_DELEGATES else "identical-alias",
        }
    from infinity_context_server.memory_comparison_models import RetrievedMemory
    from infinity_context_server.memory_comparison_rerank import benchmark_rerank_memories

    consumers = []
    for question in (
        "Which dialogue supports Alex's move to Denver?",
        "When did Alex finish the project?",
        "How many books does Alex have?",
    ):
        memories = (
            RetrievedMemory("Alex moved to Denver after the project.", 1, 0.05, "summary"),
            RetrievedMemory(
                "D1:2 Alex: I moved to Denver after the project.",
                2,
                0.05,
                "turn",
                source_refs=("locomo:c1:session_1:D1:2:turn",),
            ),
            RetrievedMemory(
                "D1:3 Alex: I moved to Denver after the project.",
                2,
                0.05,
                "tie",
                source_refs=("locomo:c1:session_1:D1:3:turn",),
            ),
        )
        result, metadata = benchmark_rerank_memories(
            SimpleNamespace(question=question, metadata={"category": 4}), memories
        )
        consumers.append(
            {
                "question": question,
                "input": [dataclasses.asdict(x) for x in memories],
                "expected": normalized(
                    {"memories": [dataclasses.asdict(x) for x in result], "metadata": metadata}
                ),
            }
        )
    contract = {
        "base_sha": base_sha,
        "public_names": public,
        "default_order": list(single),
        "single_policy_input": dataclasses.asdict(sample),
        "single_policy_plans": single,
        "legacy_pickles": {
            name: base64.b64encode(pickle.dumps(value)).decode() for name, value in samples.items()
        },
        "legacy_reference_pickles": {
            f"{module}.{name}": base64.b64encode(
                pickle.dumps(getattr(importlib.import_module(module), name))
            ).decode()
            for module, members in nodes.items()
            for name in members
            if isinstance(members[name], (ast.ClassDef, ast.FunctionDef))
        },
        "typed_delegates": TYPED_DELEGATES,
        "helper_equivalence": equivalence,
    }
    raw = (json.dumps(list(cases.values()), separators=(",", ":")) + "\n").encode()
    contract.update({"cases_sha256": hashlib.sha256(raw).hexdigest(), "case_count": len(cases)})
    output.mkdir(parents=True)
    (output / "cases.json.gz").write_bytes(gzip.compress(raw, mtime=0))
    for name, data in {
        "contract.json": contract,
        "consumers.json": consumers,
        "ownership.json": {
            "base_sha": base_sha,
            "source_sha256": sources,
            "owners": owners,
            "bindings": {
                module: binding_inventory(importlib.import_module(module), owners, public)
                for module in nodes
            },
            "definitions": {
                f"{module}.{name}": hashlib.sha256(
                    ast.dump(node, include_attributes=False).encode()
                ).hexdigest()
                for module, members in nodes.items()
                for name, node in members.items()
            },
        },
    }.items():
        (output / name).write_text(json.dumps(data, indent=2) + "\n")
    print(
        f"captured {len(cases)} complete scoring cases; "
        f"gzip {len(gzip.compress(raw, mtime=0))} bytes"
    )


def supplement(base_sha, output):
    """Add activation coverage only from independently verified unchanged original sources."""
    sources, _ = original_sources(base_sha)
    manifest = json.loads((output / "ownership.json").read_text())
    contract = json.loads((output / "contract.json").read_text())
    assert sources == manifest["source_sha256"]
    assert not (output / "activation_cases.json.gz").exists()
    score, policies = importlib.import_module(SCORE), importlib.import_module(POLICIES)
    origins = {}
    for module in (score, policies):
        expected_path = (
            Path.cwd()
            / "packages/infinity_context_server/infinity_context_server"
            / (module.__name__.rsplit(".", 1)[-1] + ".py")
        ).resolve()
        assert Path(module.__file__).resolve() == expected_path
        origins[module.__name__] = str(expected_path)
        assert (
            binding_inventory(module, manifest["owners"], contract["public_names"])
            == (manifest["bindings"][module.__name__])
        ), "Original source/global contracts must still match the pre-move oracle"
    base = scoring_features(contract["single_policy_input"], score)
    cases = []
    for overrides in (
        {
            "evidence_need": ("negative_absence",),
            "negation_surface": True,
            "query_roles": ("negative_support",),
        },
        {
            "evidence_need": ("value_support",),
            "covered_answer_unit_shapes": ("quantity_dollar",),
            "query_roles": ("value_support",),
        },
    ):
        for locality in (-1.0, 0.0, 0.449999, 0.45, 0.649999, 0.65, 1.0):
            for broad in (False, True):
                features = dataclasses.replace(
                    base, **overrides, source_locality_score=locality, broad_summary=broad
                )
                result = score.score_benchmark_rerank_candidate(features)
                plan = policies.score_rerank_policy_contributions(features)
                cases.append(
                    {
                        "input": dataclasses.asdict(features),
                        "expected": normalized(
                            {
                                "score": dataclasses.asdict(result),
                                "plan": plan.to_diagnostics(),
                                "signals": plan.score_signals,
                            }
                        ),
                    }
                )
    raw = (json.dumps(cases, separators=(",", ":")) + "\n").encode()
    (output / "activation_cases.json.gz").write_bytes(gzip.compress(raw, mtime=0))
    contract.update(
        {
            "activation_cases_sha256": hashlib.sha256(raw).hexdigest(),
            "activation_case_count": len(cases),
            "activation_source_sha256": sources,
            "activation_module_origins": origins,
        }
    )
    (output / "contract.json").write_text(json.dumps(contract, indent=2) + "\n")
    print(f"supplemented {len(cases)} activation cases from unchanged original source contracts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--supplement", action="store_true")
    args = parser.parse_args()
    (supplement if args.supplement else capture)(args.base_sha, args.output)


if __name__ == "__main__":
    main()
