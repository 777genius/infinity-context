"""Fresh activation shares the full-run cross-layer secret gate."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)
from infinity_context_server.publishable_fresh_chain_canary.authorization import (
    FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
)
from infinity_context_server.publishable_fresh_chain_canary.layout import (
    FRESH_CHAIN_STATE_DIRECTORY,
)
from infinity_context_server.publishable_fresh_chain_canary.orchestrator import (
    FreshChainCanaryOrchestrator,
)
from test_publishable_fresh_chain_canary_orchestrator import _Factory, _prepared


def test_cross_layer_secret_reuse_fails_before_fresh_state_or_provider_open(
    tmp_path: Path,
) -> None:
    files = _prepared(tmp_path)
    reused = files.secrets.publication_receipt_authentication_key.hex()
    secrets = replace(
        files.secrets,
        adapter_secrets_json=json.dumps({"nested": {"provider_key_hex": reused}}).encode(),
    )
    factory = _Factory()
    fresh_root = files.config.publication_receipt_path.parent / FRESH_CHAIN_STATE_DIRECTORY

    with pytest.raises(PublishableRunError, match="publishable_run_cross_layer_secret_reuse"):
        FreshChainCanaryOrchestrator(factory).run(
            config=files.config,
            secrets=secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )

    assert not fresh_root.exists()
    assert factory.open_count == 0
