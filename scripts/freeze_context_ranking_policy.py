"""Capture ranking outputs from unchanged pinned production before owner consolidation.

Run with the worktree packages and tests on PYTHONPATH. Expected outputs must never
be regenerated after moving production code; capture verifies the original blobs.
"""

from __future__ import annotations

import base64
import dataclasses
import functools
import gzip
import hashlib
import importlib
import inspect
import json
import pickle
import subprocess
from pathlib import Path
from typing import get_type_hints

import pytest
from context_ranking_contract_support import BASE_SHA, FIXTURES, encode

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "infinity_context_core.application."
RANKING = PREFIX + "context_ranking"
OPERATIONS = {
    RANKING: (
        "dedupe_rank_items",
        "apply_rank_fusion_boosts",
        "reciprocal_rank_fusion_scores",
        "apply_bm25_lexical_boosts",
        "apply_query_plan_bm25_lexical_boosts",
        "apply_query_anchor_intent_boosts",
        "apply_context_requirement_boosts",
        "apply_deterministic_rerank_adjustments",
        "best_query_relevance",
        "keyword_chunk_score",
        "keyword_chunk_source_score_boost",
        "apply_keyword_chunk_source_score_boost",
        "query_expansion_reason_priority",
    ),
    PREFIX + "context_rank_dedupe": ("dedupe_rank_items",),
    PREFIX + "context_query_relevance_ranking": (
        "query_relevance_rank_key",
        "query_reason_priority_for_relevance",
    ),
    PREFIX + "context_canonical_fact_retrieval": (
        "rank_fact_matches_for_query",
        "canonical_fact_match",
    ),
}
OWNERS = (
    "context_ranking",
    "context_rank_dedupe",
    "context_rank_fusion",
    "context_bm25_ranking",
    "context_query_relevance_ranking",
    "context_keyword_ranking",
    "context_anchor_intent_ranking",
    "context_requirement_ranking",
    "context_requirement_signals",
    "context_rerank_relevance",
    "context_rerank_evidence_signals",
    "context_rerank_domain_heuristics",
)


def _assert_base_sources():
    hashes = {}
    for name in OWNERS:
        relative = f"packages/infinity_context_core/infinity_context_core/application/{name}.py"
        current = (ROOT / relative).read_bytes()
        original = subprocess.check_output(["git", "show", f"{BASE_SHA}:{relative}"], cwd=ROOT)
        if current != original:
            raise RuntimeError(f"Refusing capture from modified production: {relative}")
        hashes[relative] = hashlib.sha256(original).hexdigest()
    return hashes


def _metadata():
    module = importlib.import_module(RANKING)
    definitions = {}
    for name, value in vars(module).items():
        if not (inspect.isfunction(value) or inspect.isclass(value)):
            continue
        if value.__module__ != RANKING:
            continue
        globals_record = {}
        functions = (
            [value]
            if inspect.isfunction(value)
            else [method for method in vars(value).values() if inspect.isfunction(method)]
        )
        for function in functions:
            for key in function.__code__.co_names:
                if key not in function.__globals__:
                    continue
                bound = function.__globals__[key]
                if inspect.isfunction(bound) or inspect.isclass(bound):
                    globals_record[key] = [bound.__module__, bound.__qualname__]
        instance_record = {}
        if dataclasses.is_dataclass(value):
            from infinity_context_core.application.dto import ContextItem

            sample = ContextItem(
                item_id="private-dto", item_type="chunk", text="Evidence", score=0.7, source_refs=()
            )
            values = {
                "item": sample,
                "term_frequencies": (1,),
                "length": 1,
                "text_counts": {"evidence": 1},
                "normalized_score": 0.5,
                "query_term_count": 1,
                "matched_term_count": 1,
                "query_reason": "original_query",
                "query_coverage": 1.0,
                "boost": 0.01,
                "penalty": 0.0,
                "reasons": ("frozen",),
                "rank_signals": (("frozen", 1.0),),
                "source_count": 1,
                "strong_source_count": 1,
                "coverage_ratio": 1.0,
                "anchor_conflict": False,
                "ratio": 0.0,
                "matches_query_person": True,
                "has_anchor_conflict": False,
                "topic_hits": 1,
                "covers_topic": True,
                "explicit_topic_decoy_shape": False,
            }
            instance = value(
                **{
                    field.name: values.get(field.name, frozenset())
                    for field in dataclasses.fields(value)
                }
            )
            instance_record = {
                "instance_pickle": base64.b64encode(pickle.dumps(instance)).decode(),
                "fields": [field.name for field in dataclasses.fields(value)],
                "instance_fields": encode(
                    {
                        field.name: getattr(instance, field.name)
                        for field in dataclasses.fields(value)
                    }
                ),
            }
        definitions[name] = {
            "signature": str(inspect.signature(value)),
            "annotations": {
                key: str(annotation) for key, annotation in get_type_hints(value).items()
            },
            "doc": inspect.getdoc(value),
            "pickle": base64.b64encode(pickle.dumps(value)).decode(),
            "globals": globals_record,
            **instance_record,
        }
    return definitions


class Capture:
    def __init__(self):
        self.test = "manual"
        self.depth = 0
        self.cases = []
        self.seen = set()
        self.originals = []

    def pytest_runtest_setup(self, item):
        self.test = item.nodeid

    def install(self):
        for module_name, names in OPERATIONS.items():
            module = importlib.import_module(module_name)
            for name in names:
                function = getattr(module, name)
                self.originals.append((module, name, function))
                setattr(module, name, self.wrap(module_name, name, function))

    def restore(self):
        for module, name, function in self.originals:
            setattr(module, name, function)

    def wrap(self, module, name, function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            outer = self.depth == 0
            if outer:
                inputs = encode((args, kwargs))
            self.depth += 1
            try:
                result = function(*args, **kwargs)
            finally:
                self.depth -= 1
            if outer:
                case = {
                    "test": self.test,
                    "module": module,
                    "function": name,
                    "input": inputs,
                    "output": encode(result),
                }
                if args:
                    case["same_argument"] = result is args[0]
                    if isinstance(result, tuple) and isinstance(args[0], tuple):
                        case["same_members"] = [
                            [index for index, old in enumerate(args[0]) if item is old]
                            for item in result
                        ]
                fingerprint = hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()
                if fingerprint not in self.seen:
                    self.seen.add(fingerprint)
                    self.cases.append(case)
            return result

        return wrapped


def main():
    hashes = _assert_base_sources()
    metadata = _metadata()
    capture = Capture()
    capture.install()
    try:
        status = pytest.main(
            [
                "-q",
                "--assert=plain",
                "-p",
                "no:cacheprovider",
                "tests/unit/test_context_ranking.py",
                "tests/unit/test_context_policy_behavior_snapshots.py",
                "tests/unit/test_context_answer_shape_ranking.py",
                "tests/unit/test_context_canonical_fact_retrieval.py",
                "tests/unit/test_context_ranked_evidence_paired_reservation.py",
            ],
            plugins=[capture],
        )
    finally:
        capture.restore()
    if status != 0:
        raise RuntimeError(f"Unchanged-source characterization failed: {status}")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(capture.cases, separators=(",", ":")).encode()
    packed = gzip.compress(raw, mtime=0)
    (FIXTURES / "cases.json.gz").write_bytes(packed)
    (FIXTURES / "contracts.json").write_text(
        json.dumps(
            {
                "base_sha": BASE_SHA,
                "source_sha256": hashes,
                "definitions": metadata,
                "procedure": (
                    "PYTHONPATH=<worktree packages>:<worktree tests> "
                    "python scripts/freeze_context_ranking_policy.py"
                ),
                "cases": {
                    "file": "cases.json.gz",
                    "count": len(capture.cases),
                    "encoding": "gzip deterministic mtime=0; compact UTF-8 JSON",
                    "sha256": hashlib.sha256(packed).hexdigest(),
                    "uncompressed_sha256": hashlib.sha256(raw).hexdigest(),
                    "uncompressed_bytes": len(raw),
                    "compressed_bytes": len(packed),
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Frozen {len(capture.cases)} complete ranking cases from unchanged {BASE_SHA}")


if __name__ == "__main__":
    main()
