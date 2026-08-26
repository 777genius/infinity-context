"""Narrow process-local authorization for the fixed fresh-chain 1+4 plan."""

from __future__ import annotations

from typing import final

from .ledger_models import (
    FRESH_CHAIN_CASE_ID,
    FRESH_CHAIN_EXPECTED_PHYSICAL_CALL_COUNT,
    FRESH_CHAIN_STAGES,
    canonical_sha256,
)

FRESH_CHAIN_LIVE_1_PLUS_4_FLAG = "--allow-live-1-plus-4"


@final
class FreshChainOnePlusFourAuthorization:
    """Exact capability minted only after the CLI observes the exact flag once."""

    __slots__ = ()

    @property
    def commitment_sha256(self) -> str:
        return canonical_sha256(self.material())

    @staticmethod
    def material() -> dict[str, object]:
        return {
            "authorization_flag": FRESH_CHAIN_LIVE_1_PLUS_4_FLAG,
            "case_id": FRESH_CHAIN_CASE_ID,
            "expected_physical_call_count": FRESH_CHAIN_EXPECTED_PHYSICAL_CALL_COUNT,
            "ordered_stages": list(FRESH_CHAIN_STAGES),
            "publishable": False,
            "schema_version": "memory-comparison-fresh-chain-authorization.v1",
        }


# Identity, rather than a caller-supplied string or boolean, is checked at the
# application boundary. This capability authorizes no case or count override.
FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION = FreshChainOnePlusFourAuthorization()


__all__ = (
    "FRESH_CHAIN_LIVE_1_PLUS_4_FLAG",
    "FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION",
    "FreshChainOnePlusFourAuthorization",
)
