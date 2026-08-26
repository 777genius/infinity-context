"""Fail-closed mapping for the server-owned Contract-C projection seam."""

from datetime import datetime


def typed_retrieval_projection(metadata: object) -> dict[str, object] | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("_retrieval_projection_contract")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("typed retrieval projection is malformed")
    expected = {
        "schema_version",
        "locator",
        "source_key",
        "projection_generation",
        "sequence_ordinal",
        "actor_keys",
        "time_interval",
        "relative_time_interval",
        "kind",
        "category",
        "tags",
    }
    if set(value) != expected or value["schema_version"] != "document-retrieval-projection.v1":
        raise ValueError("typed retrieval projection fields are invalid")
    absolute = value["time_interval"]
    relative = value["relative_time_interval"]
    return {
        "locator": value["locator"],
        "source_key": value["source_key"],
        "projection_generation": value["projection_generation"],
        "sequence_ordinal": value["sequence_ordinal"],
        "actor_keys": list(value["actor_keys"]),
        "start_at": None if absolute is None else _utc(absolute["start_at"]),
        "end_at": None if absolute is None else _utc(absolute["end_at"]),
        "relative_start_ms": None if relative is None else relative["start_ms"],
        "relative_end_ms": None if relative is None else relative["end_ms"],
        "kind": value["kind"],
        "category": value["category"],
        "tags": list(value["tags"]),
    }


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


__all__ = ("typed_retrieval_projection",)
