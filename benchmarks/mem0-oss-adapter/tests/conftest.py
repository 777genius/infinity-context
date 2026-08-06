from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from mem0_oss_adapter.usage import (
    FIXED_EXTRACTION_MODEL,
    RunUsageAggregate,
    UsageEvidenceError,
)


class FakeOssPort:
    def __init__(
        self,
        *,
        configured: bool = True,
        extraction_mode: Literal["raw_passthrough", "subscription_llm"] = "raw_passthrough",
    ) -> None:
        self._configured = configured
        self._extraction_mode = extraction_mode
        self.add_calls: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = []
        self.usage_rows: list[tuple[str, str, str]] = []

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def extraction_mode(self) -> Literal["raw_passthrough", "subscription_llm"]:
        return self._extraction_mode

    def add(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        user_id: str,
        agent_id: str | None,
        run_id: str,
        metadata: Mapping[str, Any],
        timestamp: int,
        mode_override: Literal["raw_passthrough", "subscription_llm"] | None = None,
    ) -> Mapping[str, Any]:
        index = len(self.rows) + 1
        stored_metadata = dict(metadata)
        created_at = datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")
        created_at = created_at.replace("+00:00", "Z")
        stored_metadata.pop("created_at", None)
        row = {
            "id": f"memory-{index}",
            "memory": messages[-1]["content"],
            "created_at": created_at,
            "metadata": stored_metadata,
            "user_id": user_id,
            "run_id": run_id,
        }
        self.rows.append(row)
        self.add_calls.append(
            {
                "agent_id": agent_id,
                "mode_override": mode_override,
                "timestamp": timestamp,
                "row": row,
            }
        )
        mode = mode_override or self._extraction_mode
        created_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self.usage_rows.append((run_id, mode, created_at))
        return {"id": row["id"], "results": [{"id": row["id"]}]}

    def get_all(self, *, filters: Mapping[str, Any], limit: int) -> Mapping[str, Any]:
        assert 1 <= limit <= 1000
        result = []
        for row in self.rows:
            metadata = row["metadata"]
            if all(
                (
                    row.get(key) == value
                    if key in {"user_id", "run_id"}
                    else metadata.get(key) == value
                )
                for key, value in filters.items()
            ):
                result.append(row)
        return {"results": result[:limit]}

    def search(
        self,
        *,
        query: str,
        filters: Mapping[str, Any],
        top_k: int,
    ) -> Mapping[str, Any]:
        del query
        return {"results": self.get_all(filters=filters, limit=top_k)["results"]}

    def delete_memories(self, *, user_id: str, run_id: str) -> bool:
        self.rows = [
            row for row in self.rows if row["user_id"] != user_id or row["run_id"] != run_id
        ]
        return True

    def delete_source_memories(
        self,
        *,
        user_id: str,
        run_id: str,
        source_id: str,
        source_sha256: str,
    ) -> bool:
        self.rows = [
            row
            for row in self.rows
            if not (
                row["user_id"] == user_id
                and row["run_id"] == run_id
                and row["metadata"].get("source_id") == source_id
                and row["metadata"].get("source_sha256") == source_sha256
            )
        ]
        return True

    def usage_for_run(self, *, run_id: str) -> RunUsageAggregate:
        entries = [entry for entry in self.usage_rows if entry[0] == run_id]
        if not entries:
            raise UsageEvidenceError("usage evidence is unavailable for the exact run")
        modes = {entry[1] for entry in entries}
        if len(modes) != 1:
            raise UsageEvidenceError("usage evidence contains mixed modes")
        mode = entries[0][1]
        timestamps = [entry[2] for entry in entries]
        extraction_calls = 1 if mode == "subscription_llm" else 0
        return RunUsageAggregate(
            mode=mode,
            operation_count=len(entries),
            extraction_calls=extraction_calls,
            request_bytes=128 if extraction_calls else 0,
            response_bytes=256 if extraction_calls else 0,
            model=FIXED_EXTRACTION_MODEL,
            first_operation_at=min(timestamps),
            last_operation_at=max(timestamps),
        )
