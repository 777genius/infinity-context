import asyncio
import json
from datetime import UTC, datetime

from infinity_context_core.application.use_cases.blob_storage_cleanup import (
    BlobStorageCleanupDecision,
)
from infinity_context_core.application.use_cases.blob_storage_integrity import (
    BlobStorageIntegrityIssue,
)
from infinity_context_server.admin import (
    _cleanup_decision_payload,
    _json_safe_dataclass_payload,
    audit_asset_storage,
)


def test_cleanup_decision_payload_is_json_safe() -> None:
    payload = _cleanup_decision_payload(
        BlobStorageCleanupDecision(
            action="would_delete",
            reason="orphan_blob",
            storage_key_hash="abc123",
            storage_key_extension=".txt",
            storage_key_path_depth=4,
            byte_size=10,
            updated_at=datetime(2026, 6, 19, tzinfo=UTC),
        )
    )

    assert payload["updated_at"] == "2026-06-19T00:00:00+00:00"
    json.dumps(payload)


def test_integrity_issue_payload_is_json_safe() -> None:
    payload = _json_safe_dataclass_payload(
        BlobStorageIntegrityIssue(
            source_type="asset",
            source_id="asset_1",
            reason="missing_blob",
            storage_key_hash="abc123",
            storage_key_extension=".png",
            storage_key_path_depth=4,
            expected_byte_size=100,
            created_at=datetime(2026, 6, 19, tzinfo=UTC),
        )
    )

    assert payload["created_at"] == "2026-06-19T00:00:00+00:00"
    json.dumps(payload)


def test_audit_asset_storage_refuses_conflicting_source_flags() -> None:
    async def run() -> None:
        result = await audit_asset_storage(
            prefix="",
            limit=10,
            max_blob_read_bytes=100,
            no_checksum=False,
            assets_only=True,
            artifacts_only=True,
        )

        assert result["status"] == "refused"

    asyncio.run(run())
