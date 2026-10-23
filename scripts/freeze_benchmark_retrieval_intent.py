"""Freeze original intent contracts and full real-consumer outputs before source moves."""

from __future__ import annotations

import argparse
import ast
import base64
import dataclasses
import gzip
import hashlib
import json
import pickle
import subprocess
from pathlib import Path
from types import SimpleNamespace

from benchmark_policy_contract_inventory import binding_inventory, intent_owners, public_names

SOURCE = Path(
    "packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py"
)
TESTS = (
    "test_memory_comparison_benchmark.py",
    "test_memory_comparison_evidence.py",
    "test_memory_comparison_source_grounding_rerank.py",
    "test_memory_comparison_relation_support.py",
    "test_memory_comparison_query_plan.py",
    "test_memory_comparison_answer_context_precision.py",
)


def normalized(value):
    return json.loads(json.dumps(value))


def capture(base_sha: str, output: Path) -> dict[str, object]:
    original = subprocess.check_output(["git", "show", f"{base_sha}:{SOURCE.as_posix()}"])
    assert SOURCE.read_bytes() == original, "Refuse oracle capture from changed production"
    from infinity_context_server import memory_comparison_intent as policy
    from infinity_context_server.memory_comparison_rerank import query_retrieval_intent

    owners = intent_owners(original.decode())
    questions = {"", "What happened?", "Why did Alex move?", "How many pets does Alex have?"}
    for filename in TESTS:
        tree = ast.parse((Path("tests/unit") / filename).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.keyword)
                and node.arg in {"question", "query"}
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                questions.add(node.value.value)
    cases = []
    categories = set()
    for question in sorted(questions):
        for category in (1, 2, 3, 4, None):
            result = query_retrieval_intent(
                SimpleNamespace(question=question, metadata={"category": category})
            )
            categories.update(item.category for item in result.relation_intents)
            cases.append(
                {
                    "category": category,
                    "intent": dataclasses.asdict(result),
                    "diagnostics": result.to_diagnostics(),
                    "profile": result.to_query_profile(),
                }
            )
    needs = sorted(
        {
            "single_fact",
            "multi_hop",
            "temporal_support",
            "temporal_sequence",
            "contrast",
            "negative_absence",
            "count_support",
            "list_support",
            "value_support",
            "location_support",
            "visual_evidence",
            "preference",
            "causal_support",
            "inference_support",
            *(str(config["evidence_need"]) for config in policy._RELATION_FACET_CONFIG.values()),
        }
    )
    roles = []
    for evidence_need in [(), *((need,) for need in needs), tuple(needs)]:
        for category in (None, 1, 2, 3, 4):
            roles.append(
                {
                    "input": {"evidence_need": evidence_need, "benchmark_category": category},
                    "expected": policy.infer_bundle_evidence_roles(
                        evidence_need=evidence_need, benchmark_category=category
                    ),
                }
            )
    times = []
    for temporal in (False, True):
        for terms in (
            (),
            ("duration",),
            ("before",),
            ("last week",),
            ("first trip",),
            ("duration", "after"),
            ("today",),
            ("date",),
        ):
            for surface in ((), ("2026-10-23",)):
                inputs = {
                    "is_temporal": temporal,
                    "temporal_terms": terms,
                    "temporal_surface_terms": surface,
                }
                times.append({"input": inputs, "expected": policy.infer_time_intent_kind(**inputs)})
    risks = []
    time = policy.RetrievalTimeIntent(False, (), (), "none")
    for entity_count in (0, 1, 3):
        for relations in ((), ("activity",)):
            for variants in ((), tuple(str(index) for index in range(20))):
                inputs = {
                    "entity_count": entity_count,
                    "relation_terms": relations,
                    "relation_variant_terms": variants,
                }
                risks.append(
                    {
                        "input": inputs,
                        "expected": policy.infer_risk_flags(**inputs, time_intent=time),
                    }
                )
    sample = query_retrieval_intent(
        SimpleNamespace(
            question="Why did Alex move to Denver after the promotion?", metadata={"category": 1}
        )
    )
    samples = {
        "RetrievalIntent": sample,
        "RetrievalTimeIntent": sample.time_intent,
        "RetrievalEntityIntent": policy.RetrievalEntityIntent("alex", ("alex",), ("alex",)),
        "RetrievalRelationIntent": policy.RetrievalRelationIntent(
            "activity", ("read",), ("books",), "activity_support", ("relation_terms",)
        ),
    }
    pickles = {
        name: base64.b64encode(pickle.dumps(value)).decode() for name, value in samples.items()
    }
    reference_pickles = {
        name: base64.b64encode(pickle.dumps(getattr(policy, name))).decode()
        for name in public_names()
    }
    output.mkdir(parents=True, exist_ok=True)
    files = {
        "ownership.json": {
            "base_sha": base_sha,
            "source_sha256": hashlib.sha256(original).hexdigest(),
            "owners": owners,
            "bindings": binding_inventory(policy, owners),
        },
        "contract.json": {
            "base_sha": base_sha,
            "public_names": public_names(),
            "legacy_pickles": pickles,
            "legacy_reference_pickles": reference_pickles,
            "facet_order": list(policy._RELATION_FACET_CONFIG),
            "coverage": {
                "questions": len(questions),
                "consumer_cases": len(cases),
                "relation_categories": sorted(categories),
                "role_needs": needs,
            },
        },
        "cases.json": cases,
        "roles.json": roles,
        "times.json": times,
        "risks.json": risks,
    }
    for filename, data in files.items():
        if filename == "cases.json":
            # Keep each complete frozen case on one line for reviewable fixture diffs.
            rendered = "[\n" + ",\n".join(json.dumps(case) for case in data) + "\n]"
            raw = (rendered + "\n").encode()
            (output / "cases.json.gz").write_bytes(gzip.compress(raw, mtime=0))
            files["contract.json"]["cases_sha256"] = hashlib.sha256(raw).hexdigest()
            continue
        else:
            rendered = json.dumps(data, ensure_ascii=False, indent=2)
        (output / filename).write_text(rendered + "\n")
    # The hash is populated while writing cases, after the first contract entry.
    (output / "contract.json").write_text(json.dumps(files["contract.json"], indent=2) + "\n")
    return files["contract.json"]["coverage"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(capture(arguments.base_sha, arguments.output)))


if __name__ == "__main__":
    main()
