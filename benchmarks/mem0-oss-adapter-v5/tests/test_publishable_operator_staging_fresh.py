"""Fresh-canary staging activation integration tests."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from infinity_context_server.publishable_durable_scheduler.publishable_run_config import (
    load_publishable_run_files,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PUBLISHABLE_RUN_SECRETS_SCHEMA,
    PublishableRunProviderInputs,
)
from publishable_mem0_v5.fresh_chain_provider_config import (
    FRESH_CHAIN_PROVIDER_SECRETS_SCHEMA,
    parse_fresh_chain_provider_inputs,
)
from publishable_operator_staging_cases import _adapter_secrets, _build


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_fresh_state_parent_is_emitted_owned_private_and_exact_documents_parse(
    tmp_path: Path,
) -> None:
    bundle = _build(tmp_path)
    fresh = json.loads(bundle.fresh_config_path.read_bytes())
    state_parent = Path(fresh["state"]["publication_receipt_path"]).parent

    assert state_parent == bundle.run_private_root / "fresh-chain-state-r17-6f2c"
    assert state_parent.is_dir()
    assert state_parent.lstat().st_uid == bundle.run_private_root.lstat().st_uid
    assert _mode(state_parent) == 0o700

    fresh_adapter = fresh["adapter"]
    secrets = {
        "adapter": {
            "fresh_chain": {
                "infinity_auth_token": "fresh-infinity-bearer-" + "z" * 32,
                "one_shot_hmac_key_hex": "16" * 32,
            },
            "run_provider": _adapter_secrets(fresh_adapter["run_provider"]),
            "schema_version": FRESH_CHAIN_PROVIDER_SECRETS_SCHEMA,
        },
        "keys": {
            "official_case_authentication_key_hex": "01" * 32,
            "locomo_scheduler_authentication_key_hex": "02" * 32,
            "longmemeval_scheduler_authentication_key_hex": "03" * 32,
            "suite_seal_authentication_key_hex": "04" * 32,
            "publication_receipt_authentication_key_hex": "05" * 32,
        },
        "schema_version": PUBLISHABLE_RUN_SECRETS_SCHEMA,
    }
    bundle.fresh_secrets_path.write_text(
        json.dumps(secrets, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    bundle.fresh_secrets_path.chmod(0o600)
    outer_config, outer_secrets = load_publishable_run_files(
        private_root=bundle.run_private_root,
        config_path=bundle.fresh_config_path,
        secrets_path=bundle.fresh_secrets_path,
    )
    provider_root = state_parent / "fresh-chain-parser-state"
    provider_root.mkdir(mode=0o700)
    provider_config, provider_secrets = parse_fresh_chain_provider_inputs(
        PublishableRunProviderInputs(
            state_root=provider_root,
            adapter_config_json=outer_config.adapter_config_json,
            adapter_secrets_json=outer_secrets.adapter_secrets_json,
        )
    )

    assert provider_config.managed_v5_live_config_path == (
        tmp_path / "public-authorities-r17-6f2c" / "managed-v5-live-config-r17-6f2c.json"
    )
    assert provider_config.infinity_retrieval_database_path.parent == state_parent
    assert repr(provider_secrets) == "FreshChainProviderSecrets(<redacted>)"
