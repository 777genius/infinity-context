"""Synthetic selector checks runnable without installed third-party dependencies."""

import asyncio
import unittest
from dataclasses import replace

from infinity_context_adapters.features.context_building.qdrant_candidate_provider import (
    translate_qdrant_locator_filters,
)
from infinity_context_core.features.context_building.application.locator_retrieval import (
    LocatorProviderRegistration,
    RetrieveLocators,
    _validated_request_copy,
)
from infinity_context_core.features.context_building.domain.locator_retrieval import (
    CanonicalLocatorCandidate,
    CanonicalLocatorRead,
    LocatorHardFilters,
    LocatorProviderHit,
    LocatorProviderResult,
    LocatorQueryVariant,
    LocatorRetrievalBounds,
    LocatorRetrievalCapability,
    LocatorRetrievalRequest,
    LocatorRetrievalScope,
    LocatorSoftPreferences,
    LocatorSourceGeneration,
    candidate_matches_request,
)


def request(thread_id=None, mode="exact"):
    return LocatorRetrievalRequest(
        "context-retrieval.v2",
        "a" * 64,
        "profile",
        LocatorRetrievalScope("space", "room", thread_id, mode),
        (LocatorQueryVariant("q", "meeting decision"),),
        LocatorHardFilters(
            source_generations=(LocatorSourceGeneration("source", "generation"),),
            excluded_source_keys=("excluded",),
        ),
        LocatorSoftPreferences(),
        LocatorRetrievalBounds(),
    )


def candidate(thread_id):
    return CanonicalLocatorCandidate(
        locator="locator",
        canonical_identity="identity",
        canonical_version=1,
        lifecycle_status="active",
        space_id="space",
        memory_scope_id="room",
        source_key="source",
        document_key="document",
        chunk_key="chunk",
        projection_generation="generation",
        kind="turn",
        category="human",
        read_snapshot="snapshot",
        thread_id=thread_id,
    )


class ThreadSelectorTests(unittest.TestCase):
    def test_any_and_exact_partitions(self):
        candidates = [candidate(thread) for thread in ("meeting-a", "meeting-b", None)]
        for thread, mode, expected in (
            (None, "any", [True, True, True]),
            (None, "exact", [False, False, True]),
            ("meeting-a", "exact", [True, False, False]),
        ):
            validated = _validated_request_copy(request(thread, mode))
            self.assertEqual(
                [candidate_matches_request(item, validated) for item in candidates], expected
            )

    def test_any_retains_canonical_fences(self):
        admitted = candidate("meeting-b")
        for changes in (
            {"space_id": "other"},
            {"memory_scope_id": "other-room"},
            {"projection_generation": "stale"},
            {"source_key": "excluded"},
            {"source_key": "unadmitted"},
            {"lifecycle_status": "deleted"},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(
                    candidate_matches_request(replace(admitted, **changes), request(mode="any"))
                )

    def test_invalid_internal_selectors_fail_closed(self):
        for thread, mode in (("meeting", "any"), (None, "all"), (None, None)):
            with self.assertRaises(ValueError):
                request(thread, mode)
        forged = request()
        object.__setattr__(forged.scope, "thread_mode", "unknown")
        with self.assertRaises(ValueError):
            _validated_request_copy(forged)

    def test_one_global_engine_call_with_neighbors_and_final_hydration_fences(self):
        def row(key, thread, ordinal=10, **changes):
            return replace(
                candidate(thread),
                canonical_identity=key,
                locator=key,
                chunk_key=key,
                sequence_ordinal=ordinal,
                **changes,
            )

        rows = [
            row("a", "meeting-a"),
            row("b", "meeting-b", source_key="source-b", projection_generation="generation-b"),
            row("null", None),
            row("cross-space", "meeting-a", space_id="elsewhere"),
            row("cross-room", "meeting-a", memory_scope_id="elsewhere"),
            row("stale", "meeting-a", projection_generation="stale"),
            row("excluded", "meeting-a", source_key="excluded"),
        ]
        neighbors = (
            row("a-next", "meeting-a", 11),
            row(
                "b-next",
                "meeting-b",
                11,
                source_key="source-b",
                projection_generation="generation-b",
            ),
            row("null-next", None, 11),
            row("bad-gen", "meeting-a", 9, projection_generation="stale"),
        )
        for mode, thread, expected in (
            ("any", None, ["a", "b", "null"]),
            ("exact", None, ["null"]),
            ("exact", "meeting-a", ["a"]),
        ):
            calls = []

            class Provider:
                def __init__(self, recorded_calls):
                    self.recorded_calls = recorded_calls

                async def retrieve_locator_candidates(self, req):
                    self.recorded_calls.append(req)
                    return LocatorProviderResult(
                        tuple(
                            LocatorProviderHit(item.canonical_identity, 1, "lane", "q", rank)
                            for rank, item in enumerate(rows, 1)
                        )
                    )

            class Reader:
                async def hydrate_locator_candidates(self, req, identities):
                    return tuple(item for item in rows if item.canonical_identity in identities)

                async def hydrate_final_locator_read(self, req, identities, radius):
                    return CanonicalLocatorRead(
                        tuple(item for item in rows if item.canonical_identity in identities),
                        neighbors,
                    )

            engine = RetrieveLocators(
                (LocatorProviderRegistration("lane", Provider(calls), required=True),),
                Reader(),
                LocatorRetrievalCapability("a" * 64, "profile", supports_neighbors=True),
            )
            req = request(thread, mode)
            req = replace(
                req,
                bounds=replace(req.bounds, neighbor_radius=1),
                hard_filters=replace(
                    req.hard_filters,
                    source_generations=(
                        LocatorSourceGeneration("source", "generation"),
                        LocatorSourceGeneration("source-b", "generation-b"),
                    ),
                ),
            )
            result = asyncio.run(engine.execute(req))
            self.assertEqual([item.canonical_identity for item in result.candidates], expected)
            self.assertEqual(
                [[n.canonical_identity for n in item.neighbors] for item in result.candidates],
                [[key + "-next"] for key in expected],
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].bounds, req.bounds)

    def test_qdrant_only_relaxes_thread_predicate(self):
        exact = translate_qdrant_locator_filters(request())
        any_threads = translate_qdrant_locator_filters(request(mode="any"))
        self.assertEqual(
            any_threads,
            {**exact, "must": [item for item in exact["must"] if item["key"] != "thread_id"]},
        )
        self.assertIn({"key": "thread_id", "is_null": True}, exact["must"])
        self.assertIn(
            {"key": "thread_id", "match": "meeting-a"},
            translate_qdrant_locator_filters(request("meeting-a"))["must"],
        )


if __name__ == "__main__":
    unittest.main()
