"""Order-independent radius-two neighbor regressions for Retrieval."""

import asyncio
import json
import random
from dataclasses import asdict

from infinity_context_core.features.context_building.public import (
    LocatorProviderRegistration,
    LocatorRetrievalBounds,
)
from infinity_context_core.features.context_building.tests.test_locator_retrieval import (
    _canonical,
    _hit,
    _Hydrator,
    _Provider,
    _request,
    _retrieve,
)


def test_radius_two_is_complete_under_shuffle_and_shared_neighbor_has_one_owner() -> None:
    seeds = (_canonical("seed-a", sequence_ordinal=10), _canonical("seed-b", sequence_ordinal=14))
    neighbors = [
        _canonical(f"ordinal-{ordinal}", sequence_ordinal=ordinal)
        for ordinal in (8, 9, 11, 12, 13, 15, 16)
    ]
    expected: bytes | None = None
    for shuffle_seed in range(20):
        shuffled = neighbors.copy()
        random.Random(shuffle_seed).shuffle(shuffled)
        provider = LocatorProviderRegistration(
            "dense", _Provider((_hit("seed-a", rank=1), _hit("seed-b", rank=2)))
        )
        response = asyncio.run(
            _retrieve(
                (provider,),
                _Hydrator(seeds, neighbors=tuple(shuffled)),
                supports_neighbors=True,
            ).execute(_request(bounds=LocatorRetrievalBounds(result_limit=2, neighbor_radius=2)))
        )
        encoded = json.dumps(asdict(response), sort_keys=True, separators=(",", ":")).encode()
        expected = encoded if expected is None else expected
        assert encoded == expected
        assert tuple(item.canonical_identity for item in response.candidates[0].neighbors) == (
            "ordinal-8",
            "ordinal-9",
            "ordinal-11",
            "ordinal-12",
        )
        identities = [
            item.canonical_identity
            for candidate in response.candidates
            for item in candidate.neighbors
        ]
        assert identities.count("ordinal-12") == 1
        assert len(identities) == 7
