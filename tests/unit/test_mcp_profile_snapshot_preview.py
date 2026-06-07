from __future__ import annotations

import asyncio
from typing import Any

from memo_stack_mcp.application.service import MemoryToolService
from memo_stack_mcp.config import MemoryMcpSettings
from memo_stack_mcp.domain.models import MemoryScope


class PreviewGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def preview_profile_snapshot_import(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("preview_profile_snapshot_import", kwargs))
        return {
            "data": {
                "status": "ok",
                "dry_run": True,
                "merge_strategy": kwargs["merge_strategy"],
                "preview": {
                    "would_import": {
                        "facts": 1,
                        "documents": 0,
                        "chunks": 0,
                        "relations": 1,
                        "source_refs": 1,
                    }
                },
            }
        }


def test_service_preview_profile_snapshot_import_is_read_only_and_scoped() -> None:
    async def run() -> None:
        gateway = PreviewGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                default_space_slug="project-a",
                default_profile_external_ref="backend",
            ),
        )
        snapshot = {"schema_version": 1, "facts": [{"id": "fact_1"}]}
        manifest = {"schema_version": "memo_stack.profile_snapshot_manifest.v1"}

        result = await service.preview_profile_snapshot_import(
            snapshot=snapshot,
            manifest=manifest,
            merge_strategy="skip_existing",
        )

        assert result["ok"] is True
        assert result["data"]["dry_run"] is True
        assert result["data"]["preview"]["would_import"]["facts"] == 1
        assert result["data"]["preview"]["would_import"]["relations"] == 1
        assert result["diagnostics"]["side_effects"] == []
        assert gateway.calls == [
            (
                "preview_profile_snapshot_import",
                {
                    "scope": MemoryScope("project-a", "backend", None),
                    "snapshot": snapshot,
                    "manifest": manifest,
                    "merge_strategy": "skip_existing",
                },
            )
        ]

    asyncio.run(run())
