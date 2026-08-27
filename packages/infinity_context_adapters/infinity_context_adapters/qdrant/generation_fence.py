"""Atomic-by-identity generation fencing for generic Qdrant points."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from infinity_context_core.ports.adapters import VectorUpsertItem


class QdrantCanonicalVersionError(ValueError):
    """Raised before an unversioned derived point can be written."""


def generic_generation_point_id(chunk_id: str, canonical_version: int) -> str:
    """Return an immutable identity so a late generation cannot clobber a successor."""

    return str(uuid5(NAMESPACE_URL, f"{chunk_id}:canonical-version:{canonical_version}"))


def generic_point_id_for_write(item: VectorUpsertItem) -> str:
    canonical_version = item.metadata.get("canonical_version")
    if type(canonical_version) is not int:
        raise QdrantCanonicalVersionError
    return generic_generation_point_id(item.chunk_id, canonical_version)


async def delete_older_or_unversioned(
    client: object,
    models: object,
    *,
    collection_name: str,
    chunk_ids: tuple[str, ...],
    canonical_version: int,
) -> None:
    stale_filter = models.Filter(
        must=(
            models.FieldCondition(
                key="chunk_id",
                match=models.MatchAny(any=list(chunk_ids)),
            ),
        ),
        should=(
            models.FieldCondition(
                key="canonical_version",
                range=models.Range(lt=canonical_version),
            ),
            models.IsEmptyCondition(
                is_empty=models.PayloadField(key="canonical_version")
            ),
        ),
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
    "generic_generation_point_id",
    "generic_point_id_for_write",
)
