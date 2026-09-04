"""Atomic-by-identity generation fencing for generic Qdrant points."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from infinity_context_core.ports.adapters import VectorUpsertItem

from infinity_context_adapters.qdrant.identity_evidence import qdrant_point_id_for_chunk


class QdrantCanonicalVersionError(ValueError):
    """Raised before an unversioned derived point can be written."""


def legacy_generation_point_id(chunk_id: str, canonical_version: int) -> str:
    """Identify points written by the retired generation-specific scheme."""

    return str(uuid5(NAMESPACE_URL, f"{chunk_id}:canonical-version:{canonical_version}"))


def generic_point_id_for_write(item: VectorUpsertItem) -> str:
    canonical_version = item.metadata.get("canonical_version")
    if type(canonical_version) is not int:
        raise QdrantCanonicalVersionError
    return qdrant_point_id_for_chunk(item.chunk_id)


async def delete_older_or_unversioned(
    client: object,
    models: object,
    *,
    collection_name: str,
    chunk_ids: tuple[str, ...],
    canonical_version: int,
    preserve_stable: bool,
) -> None:
    stable_point_ids = [qdrant_point_id_for_chunk(chunk_id) for chunk_id in chunk_ids]
    filter_values = {
        "must": (
            models.FieldCondition(
                key="chunk_id",
                match=models.MatchAny(any=list(chunk_ids)),
            ),
        ),
        "should": (
            models.FieldCondition(
                key="canonical_version",
                range=models.Range(lte=canonical_version),
            ),
            models.IsEmptyCondition(is_empty=models.PayloadField(key="canonical_version")),
        ),
    }
    if preserve_stable:
        filter_values["must_not"] = (models.HasIdCondition(has_id=stable_point_ids),)
    stale_filter = models.Filter(
        **filter_values,
    )
    await client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(filter=stale_filter),
        wait=True,
    )
    observed, _next_cursor = await client.scroll(
        collection_name=collection_name,
        scroll_filter=stale_filter,
        limit=1,
        with_payload=False,
        with_vectors=False,
        consistency="all",
    )
    if not isinstance(observed, (list, tuple)) or observed:
        raise RuntimeError("stale vector generations remain")


__all__ = (
    "QdrantCanonicalVersionError",
    "delete_older_or_unversioned",
    "generic_point_id_for_write",
    "legacy_generation_point_id",
)
