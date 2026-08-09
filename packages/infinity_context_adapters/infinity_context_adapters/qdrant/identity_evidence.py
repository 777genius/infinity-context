"""Exact Qdrant identity evidence without vectors or projection content."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkProjectionPassReceipt,
    BenchmarkUnsealedProjectionScope,
)
from infinity_context_core.ports.vector_projection_evidence import (
    VectorProjectionDeleteEvidence,
    VectorProjectionPointIdentity,
    VectorProjectionPresenceEvidence,
    VectorProjectionScope,
)

_EVIDENCE_BATCH_SIZE = 256
_EVIDENCE_SCROLL_PAGE_SIZE = 256
_MAX_EVIDENCE_POINTS = 100_000
_IDENTITY_PAYLOAD_FIELDS = (
    "chunk_id",
    "space_id",
    "memory_scope_id",
    "thread_id",
    "projection_version",
)

_ClientFactory = Callable[[], Awaitable[tuple[object, object]]]


@dataclass(frozen=True, slots=True)
class _ProjectionSnapshot:
    observed: tuple[VectorProjectionPointIdentity, ...]
    scoped_point_ids: tuple[str, ...]
    exact_scoped_count: int
    issues: tuple[str, ...]


class QdrantIdentityEvidence:
    """Provider-specific implementation of exact projection identity evidence."""

    def __init__(
        self,
        *,
        client_factory: _ClientFactory,
        url: str,
        collection_name: str,
        projection_version: str,
    ) -> None:
        if not callable(client_factory):
            raise ValueError("client_factory must be callable")
        normalized_url = _normalized_provider_url(url)
        _required_identity(collection_name, "collection_name")
        _required_identity(projection_version, "projection_version")
        self._client_factory = client_factory
        self._normalized_url = normalized_url
        self._collection_name = collection_name
        self._projection_version = projection_version

    @property
    def target_commitment_sha256(self) -> str:
        return qdrant_target_commitment_sha256(
            self._normalized_url,
            self._collection_name,
        )

    async def observe_exact(
        self,
        *,
        scope: VectorProjectionScope,
        chunk_ids: tuple[str, ...],
    ) -> VectorProjectionPresenceEvidence:
        """Observe expected identities and exhaustively enumerate their scope."""

        expected = _projection_expected(
            scope,
            chunk_ids,
            configured_projection_version=self._projection_version,
        )
        client = None
        try:
            client, models = await self._client_factory()
            if not await client.collection_exists(self._collection_name):
                return VectorProjectionPresenceEvidence(
                    scope=scope,
                    target_commitment_sha256=self.target_commitment_sha256,
                    expected=expected,
                    observed=(),
                    scoped_point_ids=(),
                    exact_scoped_count=0,
                    issues=("qdrant.evidence_collection_missing",),
                )
            snapshot = await self._projection_snapshot(client, models, scope, expected)
            issues = list(snapshot.issues)
            expected_point_ids = {item.point_id for item in expected}
            if snapshot.observed != expected:
                issues.append("qdrant.evidence_expected_points_missing")
            if set(snapshot.scoped_point_ids) != expected_point_ids:
                issues.append("qdrant.evidence_scoped_identity_mismatch")
            if snapshot.exact_scoped_count != len(expected):
                issues.append("qdrant.evidence_expected_count_mismatch")
            return VectorProjectionPresenceEvidence(
                scope=scope,
                target_commitment_sha256=self.target_commitment_sha256,
                expected=expected,
                observed=snapshot.observed,
                scoped_point_ids=snapshot.scoped_point_ids,
                exact_scoped_count=snapshot.exact_scoped_count,
                issues=_unique_issues(issues),
            )
        except Exception:
            return VectorProjectionPresenceEvidence(
                scope=scope,
                target_commitment_sha256=self.target_commitment_sha256,
                expected=expected,
                observed=(),
                scoped_point_ids=(),
                exact_scoped_count=0,
                issues=("qdrant.evidence_read_failed",),
            )
        finally:
            await _close_client(client)

    async def delete_and_observe_exact(
        self,
        *,
        scope: VectorProjectionScope,
        chunk_ids: tuple[str, ...],
        pass_index: int,
    ) -> VectorProjectionDeleteEvidence:
        """Delete scope-validated identities, then exhaustively prove absence."""

        if type(pass_index) is not int or pass_index not in (1, 2):
            raise ValueError("pass_index must be 1 or 2")
        expected = _projection_expected(
            scope,
            chunk_ids,
            configured_projection_version=self._projection_version,
        )
        client = None
        try:
            client, models = await self._client_factory()
            if not await client.collection_exists(self._collection_name):
                return VectorProjectionDeleteEvidence(
                    scope=scope,
                    target_commitment_sha256=self.target_commitment_sha256,
                    pass_index=pass_index,
                    expected=expected,
                    present_before=(),
                    remaining=(),
                    scoped_point_ids_after=(),
                    exact_scoped_count_after=0,
                    delete_completed=True,
                )

            before = await self._projection_snapshot(client, models, scope, expected)
            expected_point_ids = {item.point_id for item in expected}
            before_issues = list(before.issues)
            if any(point_id not in expected_point_ids for point_id in before.scoped_point_ids):
                before_issues.append("qdrant.evidence_unexpected_scoped_point")
            if before_issues:
                return VectorProjectionDeleteEvidence(
                    scope=scope,
                    target_commitment_sha256=self.target_commitment_sha256,
                    pass_index=pass_index,
                    expected=expected,
                    present_before=before.observed,
                    remaining=before.observed,
                    scoped_point_ids_after=before.scoped_point_ids,
                    exact_scoped_count_after=before.exact_scoped_count,
                    delete_completed=False,
                    issues=_unique_issues(
                        (*before_issues, "qdrant.evidence_delete_precondition_failed")
                    ),
                )

            result = await client.delete(
                collection_name=self._collection_name,
                points_selector=models.PointIdsList(points=[item.point_id for item in expected]),
                wait=True,
                ordering=models.WriteOrdering.STRONG,
            )
            delete_completed = _delete_completed(result)
            after = await self._projection_snapshot(client, models, scope, expected)
            issues = list(after.issues)
            if not delete_completed:
                issues.append("qdrant.evidence_delete_not_completed")
            if after.observed:
                issues.append("qdrant.evidence_delete_remaining")
            if after.scoped_point_ids:
                issues.append("qdrant.evidence_scoped_points_remaining")
            if after.exact_scoped_count:
                issues.append("qdrant.evidence_scoped_count_remaining")
            return VectorProjectionDeleteEvidence(
                scope=scope,
                target_commitment_sha256=self.target_commitment_sha256,
                pass_index=pass_index,
                expected=expected,
                present_before=before.observed,
                remaining=after.observed,
                scoped_point_ids_after=after.scoped_point_ids,
                exact_scoped_count_after=after.exact_scoped_count,
                delete_completed=delete_completed,
                issues=_unique_issues(issues),
            )
        except Exception:
            return VectorProjectionDeleteEvidence(
                scope=scope,
                target_commitment_sha256=self.target_commitment_sha256,
                pass_index=pass_index,
                expected=expected,
                present_before=(),
                remaining=expected,
                scoped_point_ids_after=(),
                exact_scoped_count_after=0,
                delete_completed=False,
                issues=("qdrant.evidence_delete_failed",),
            )
        finally:
            await _close_client(client)

    async def delete_benchmark_space_two_pass(
        self,
        *,
        space_id: str,
        scopes: tuple[BenchmarkUnsealedProjectionScope, ...],
    ) -> tuple[BenchmarkProjectionPassReceipt, BenchmarkProjectionPassReceipt]:
        """Delete only canonical points after two independent full-space scans."""

        _required_identity(space_id, "space_id")
        expected = _benchmark_expected(space_id, scopes, self._projection_version)
        receipts = []
        for pass_index in (1, 2):
            receipts.append(
                await self._delete_benchmark_space_pass(
                    space_id=space_id,
                    expected=expected,
                    pass_index=pass_index,
                )
            )
        return receipts[0], receipts[1]

    async def _delete_benchmark_space_pass(
        self,
        *,
        space_id: str,
        expected: dict[str, tuple[str, str, str | None]],
        pass_index: int,
    ) -> BenchmarkProjectionPassReceipt:
        client = None
        try:
            client, models = await self._client_factory()
            present: tuple[str, ...] = ()
            if await client.collection_exists(self._collection_name):
                globally_present = await _benchmark_expected_point_ids(
                    client,
                    collection_name=self._collection_name,
                    space_id=space_id,
                    projection_version=self._projection_version,
                    expected=expected,
                )
                scoped_present = await _benchmark_space_point_ids(
                    client,
                    models,
                    collection_name=self._collection_name,
                    space_id=space_id,
                    projection_version=self._projection_version,
                    expected=expected,
                )
                if globally_present != scoped_present:
                    raise ValueError("Qdrant recovery global and space inventories differ")
                present = globally_present
                if pass_index == 2 and present:
                    raise ValueError("Qdrant recovery second pass observed residual points")
                if present:
                    result = await client.delete(
                        collection_name=self._collection_name,
                        points_selector=models.PointIdsList(points=list(present)),
                        wait=True,
                        ordering=models.WriteOrdering.STRONG,
                    )
                    if not _delete_completed(result):
                        raise ValueError("Qdrant recovery delete was not completed")
                global_after = await _benchmark_expected_point_ids(
                    client,
                    collection_name=self._collection_name,
                    space_id=space_id,
                    projection_version=self._projection_version,
                    expected=expected,
                )
                after = await _benchmark_space_point_ids(
                    client,
                    models,
                    collection_name=self._collection_name,
                    space_id=space_id,
                    projection_version=self._projection_version,
                    expected=expected,
                )
                if global_after or after:
                    raise ValueError("Qdrant recovery space is not absent")
            digest = _json_sha256(
                {
                    "schema_version": "benchmark-qdrant-recovery-pass.v1",
                    "target_commitment_sha256": self.target_commitment_sha256,
                    "space_id": space_id,
                    "pass_index": pass_index,
                    "expected_point_ids": sorted(expected),
                    "present_before": list(present),
                    "space_count_after": 0,
                }
            )
            return BenchmarkProjectionPassReceipt(
                lane="qdrant",
                target_commitment_sha256=self.target_commitment_sha256,
                pass_index=pass_index,
                observed_count=0,
                absent=True,
                receipt_sha256=digest,
            )
        finally:
            await _close_client(client)

    async def _projection_snapshot(
        self,
        client: object,
        models: object,
        scope: VectorProjectionScope,
        expected: tuple[VectorProjectionPointIdentity, ...],
    ) -> _ProjectionSnapshot:
        expected_by_point = {item.point_id: item for item in expected}
        retrieved: dict[str, VectorProjectionPointIdentity] = {}
        issues: list[str] = []
        for start in range(0, len(expected), _EVIDENCE_BATCH_SIZE):
            point_ids = [item.point_id for item in expected[start : start + _EVIDENCE_BATCH_SIZE]]
            records = await client.retrieve(
                collection_name=self._collection_name,
                ids=point_ids,
                with_payload=list(_IDENTITY_PAYLOAD_FIELDS),
                with_vectors=False,
                consistency="all",
            )
            if not isinstance(records, (list, tuple)):
                raise TypeError("Qdrant retrieve response is invalid")
            for record in records:
                point_id, identity, record_issues = _projection_record_identity(
                    record,
                    scope,
                    expected_by_point=expected_by_point,
                )
                issues.extend(record_issues)
                if point_id is None or identity is None:
                    continue
                if point_id in retrieved:
                    issues.append("qdrant.evidence_duplicate_retrieved_point")
                    continue
                retrieved[point_id] = identity

        query_filter = _projection_scope_filter(models, scope)
        scoped_point_ids: list[str] = []
        seen_scoped: set[str] = set()
        seen_offsets: set[tuple[str, str]] = set()
        offset = None
        exhausted = False
        max_pages = (_MAX_EVIDENCE_POINTS // _EVIDENCE_SCROLL_PAGE_SIZE) + 2
        for _ in range(max_pages):
            page = await client.scroll(
                collection_name=self._collection_name,
                scroll_filter=query_filter,
                limit=_EVIDENCE_SCROLL_PAGE_SIZE,
                offset=offset,
                with_payload=list(_IDENTITY_PAYLOAD_FIELDS),
                with_vectors=False,
                consistency="all",
            )
            if not isinstance(page, (list, tuple)) or len(page) != 2:
                raise TypeError("Qdrant scroll response is invalid")
            records, next_offset = page
            if not isinstance(records, (list, tuple)):
                raise TypeError("Qdrant scroll records are invalid")
            for record in records:
                point_id, _identity, record_issues = _projection_record_identity(
                    record,
                    scope,
                )
                issues.extend(record_issues)
                if point_id is None:
                    continue
                if point_id in seen_scoped:
                    issues.append("qdrant.evidence_duplicate_scrolled_point")
                    continue
                if len(scoped_point_ids) >= _MAX_EVIDENCE_POINTS:
                    issues.append("qdrant.evidence_scroll_limit_exceeded")
                    exhausted = True
                    break
                seen_scoped.add(point_id)
                scoped_point_ids.append(point_id)
            if exhausted or next_offset is None:
                exhausted = True
                break
            offset_key = (type(next_offset).__name__, str(next_offset))
            if offset_key in seen_offsets:
                issues.append("qdrant.evidence_scroll_offset_repeated")
                exhausted = True
                break
            seen_offsets.add(offset_key)
            offset = next_offset
        if not exhausted:
            issues.append("qdrant.evidence_scroll_limit_exceeded")

        count_result = await client.count(
            collection_name=self._collection_name,
            count_filter=query_filter,
            exact=True,
        )
        exact_count = getattr(count_result, "count", None)
        if type(exact_count) is not int or exact_count < 0:
            raise TypeError("Qdrant count response is invalid")
        if exact_count != len(scoped_point_ids):
            issues.append("qdrant.evidence_scroll_count_mismatch")

        observed = tuple(item for item in expected if item.point_id in retrieved)
        return _ProjectionSnapshot(
            observed=observed,
            scoped_point_ids=tuple(scoped_point_ids),
            exact_scoped_count=exact_count,
            issues=_unique_issues(issues),
        )


def qdrant_point_id_for_chunk(chunk_id: str) -> str:
    """Return the stable Qdrant point identity for a canonical chunk."""

    _required_identity(chunk_id, "chunk_id")
    return str(uuid5(NAMESPACE_URL, chunk_id))


def qdrant_target_commitment_sha256(url: str, collection_name: str) -> str:
    """Bind evidence to adapter kind, normalized target URL, and collection."""

    normalized_url = _normalized_provider_url(url)
    _required_identity(collection_name, "collection_name")
    target_identity = (
        b"qdrant\x00" + normalized_url.encode("utf-8") + b"\x00" + collection_name.encode("utf-8")
    )
    return hashlib.sha256(target_identity).hexdigest()


def _benchmark_expected(
    space_id: str,
    scopes: tuple[BenchmarkUnsealedProjectionScope, ...],
    projection_version: str,
) -> dict[str, tuple[str, str, str | None]]:
    expected: dict[str, tuple[str, str, str | None]] = {}
    for scope in scopes:
        if type(scope) is not BenchmarkUnsealedProjectionScope:
            raise ValueError("benchmark recovery scope is invalid")
        for chunk_id in scope.chunk_ids:
            point_id = qdrant_point_id_for_chunk(chunk_id)
            if point_id in expected:
                raise ValueError("benchmark recovery points are duplicated")
            expected[point_id] = (chunk_id, scope.memory_scope_id, scope.thread_id)
    if len(expected) > _MAX_EVIDENCE_POINTS:
        raise ValueError("benchmark recovery points exceed the hard cap")
    del space_id, projection_version
    return expected


async def _benchmark_space_point_ids(
    client: object,
    models: object,
    *,
    collection_name: str,
    space_id: str,
    projection_version: str,
    expected: Mapping[str, tuple[str, str, str | None]],
) -> tuple[str, ...]:
    query_filter = models.Filter(
        must=[models.FieldCondition(key="space_id", match=models.MatchValue(value=space_id))]
    )
    point_ids: list[str] = []
    seen: set[str] = set()
    offsets: set[tuple[str, str]] = set()
    offset = None
    exhausted = False
    max_pages = (_MAX_EVIDENCE_POINTS // _EVIDENCE_SCROLL_PAGE_SIZE) + 2
    for _ in range(max_pages):
        page = await client.scroll(
            collection_name=collection_name,
            scroll_filter=query_filter,
            limit=_EVIDENCE_SCROLL_PAGE_SIZE,
            offset=offset,
            with_payload=list(_IDENTITY_PAYLOAD_FIELDS),
            with_vectors=False,
            consistency="all",
        )
        if not isinstance(page, (list, tuple)) or len(page) != 2:
            raise TypeError("Qdrant recovery scroll response is invalid")
        records, next_offset = page
        if not isinstance(records, (list, tuple)):
            raise TypeError("Qdrant recovery scroll records are invalid")
        for record in records:
            raw_id = getattr(record, "id", None)
            point_id = str(raw_id) if isinstance(raw_id, (str, int)) else ""
            payload = getattr(record, "payload", None)
            if not point_id or point_id in seen or not isinstance(payload, Mapping):
                raise ValueError("Qdrant recovery point identity is malformed")
            target = expected.get(point_id)
            if target is None:
                raise ValueError("Qdrant recovery found an unknown space point")
            chunk_id, memory_scope_id, thread_id = target
            if (
                payload.get("chunk_id") != chunk_id
                or payload.get("space_id") != space_id
                or payload.get("memory_scope_id") != memory_scope_id
                or payload.get("thread_id") != thread_id
                or payload.get("projection_version") != projection_version
                or qdrant_point_id_for_chunk(chunk_id) != point_id
            ):
                raise ValueError("Qdrant recovery point payload is malformed")
            seen.add(point_id)
            point_ids.append(point_id)
            if len(point_ids) > _MAX_EVIDENCE_POINTS:
                raise ValueError("Qdrant recovery scan exceeds the hard cap")
        if next_offset is None:
            exhausted = True
            break
        key = (type(next_offset).__name__, str(next_offset))
        if key in offsets:
            raise ValueError("Qdrant recovery scroll offset repeated")
        offsets.add(key)
        offset = next_offset
    if not exhausted:
        raise ValueError("Qdrant recovery scan did not exhaust the space")
    count = await client.count(
        collection_name=collection_name,
        count_filter=query_filter,
        exact=True,
    )
    exact_count = getattr(count, "count", None)
    if exact_count != len(point_ids):
        raise ValueError("Qdrant recovery full-space count differs from scroll")
    return tuple(sorted(point_ids))


async def _benchmark_expected_point_ids(
    client: object,
    *,
    collection_name: str,
    space_id: str,
    projection_version: str,
    expected: Mapping[str, tuple[str, str, str | None]],
) -> tuple[str, ...]:
    present: list[str] = []
    point_ids = sorted(expected)
    for start in range(0, len(point_ids), _EVIDENCE_BATCH_SIZE):
        records = await client.retrieve(
            collection_name=collection_name,
            ids=point_ids[start : start + _EVIDENCE_BATCH_SIZE],
            with_payload=list(_IDENTITY_PAYLOAD_FIELDS),
            with_vectors=False,
            consistency="all",
        )
        if not isinstance(records, (list, tuple)):
            raise TypeError("Qdrant recovery retrieve response is invalid")
        for record in records:
            raw_id = getattr(record, "id", None)
            point_id = str(raw_id) if isinstance(raw_id, (str, int)) else ""
            payload = getattr(record, "payload", None)
            target = expected.get(point_id)
            if not point_id or target is None or not isinstance(payload, Mapping):
                raise ValueError("Qdrant recovery expected point is malformed")
            chunk_id, memory_scope_id, thread_id = target
            if (
                payload.get("chunk_id") != chunk_id
                or payload.get("space_id") != space_id
                or payload.get("memory_scope_id") != memory_scope_id
                or payload.get("thread_id") != thread_id
                or payload.get("projection_version") != projection_version
                or qdrant_point_id_for_chunk(chunk_id) != point_id
            ):
                raise ValueError("Qdrant recovery expected point moved or is malformed")
            present.append(point_id)
    if len(present) != len(set(present)):
        raise ValueError("Qdrant recovery expected point is duplicated")
    return tuple(sorted(present))


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _normalized_provider_url(url: object) -> str:
    if type(url) is not str or not url or url != url.strip() or len(url) > 2048:
        raise ValueError("url must be a bounded non-blank URL")
    parsed = urlsplit(url)
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or hostname is None:
        raise ValueError("url must identify an HTTP(S) Qdrant target")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("url contains an invalid port") from exc
    normalized_host = hostname.casefold()
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = normalized_host if port is None or default_port else f"{normalized_host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _projection_expected(
    scope: VectorProjectionScope,
    chunk_ids: tuple[str, ...],
    *,
    configured_projection_version: str,
) -> tuple[VectorProjectionPointIdentity, ...]:
    if type(scope) is not VectorProjectionScope:
        raise ValueError("scope must be VectorProjectionScope")
    if scope.projection_version != configured_projection_version:
        raise ValueError("scope projection_version differs from the configured projection")
    if type(chunk_ids) is not tuple or not chunk_ids or len(chunk_ids) > _MAX_EVIDENCE_POINTS:
        raise ValueError("chunk_ids must be a bounded non-empty tuple")
    for chunk_id in chunk_ids:
        _required_identity(chunk_id, "chunk_id")
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("chunk_ids contains duplicate identities")
    return tuple(
        VectorProjectionPointIdentity(
            chunk_id=chunk_id,
            point_id=qdrant_point_id_for_chunk(chunk_id),
        )
        for chunk_id in chunk_ids
    )


def _projection_scope_filter(models: object, scope: VectorProjectionScope) -> object:
    must = [
        models.FieldCondition(
            key="space_id",
            match=models.MatchValue(value=scope.space_id),
        ),
        models.FieldCondition(
            key="memory_scope_id",
            match=models.MatchValue(value=scope.memory_scope_id),
        ),
        models.FieldCondition(
            key="projection_version",
            match=models.MatchValue(value=scope.projection_version),
        ),
    ]
    if scope.thread_id is None:
        must.append(
            models.IsNullCondition(
                is_null=models.PayloadField(key="thread_id"),
            )
        )
    else:
        must.append(
            models.FieldCondition(
                key="thread_id",
                match=models.MatchValue(value=scope.thread_id),
            )
        )
    return models.Filter(must=must)


def _projection_record_identity(
    record: object,
    scope: VectorProjectionScope,
    *,
    expected_by_point: Mapping[str, VectorProjectionPointIdentity] | None = None,
) -> tuple[str | None, VectorProjectionPointIdentity | None, tuple[str, ...]]:
    raw_point_id = getattr(record, "id", None)
    point_id = str(raw_point_id) if isinstance(raw_point_id, (str, int)) else None
    if point_id is None or not point_id or len(point_id) > 512:
        return None, None, ("qdrant.evidence_point_id_invalid",)

    payload = getattr(record, "payload", None)
    if not isinstance(payload, Mapping) or any(
        field not in payload for field in _IDENTITY_PAYLOAD_FIELDS
    ):
        return point_id, None, ("qdrant.evidence_payload_invalid",)

    issues: list[str] = []
    if (
        payload.get("space_id") != scope.space_id
        or payload.get("memory_scope_id") != scope.memory_scope_id
        or payload.get("thread_id") != scope.thread_id
        or payload.get("projection_version") != scope.projection_version
    ):
        issues.append("qdrant.evidence_scope_payload_mismatch")

    chunk_id = payload.get("chunk_id")
    if (
        type(chunk_id) is not str
        or not chunk_id
        or chunk_id != chunk_id.strip()
        or len(chunk_id) > 512
    ):
        issues.append("qdrant.evidence_chunk_id_invalid")
        return point_id, None, _unique_issues(issues)
    if qdrant_point_id_for_chunk(chunk_id) != point_id:
        issues.append("qdrant.evidence_point_mapping_mismatch")

    expected = expected_by_point.get(point_id) if expected_by_point is not None else None
    if expected_by_point is not None and expected is None:
        issues.append("qdrant.evidence_unexpected_retrieved_point")
    elif expected is not None and expected.chunk_id != chunk_id:
        issues.append("qdrant.evidence_chunk_mapping_mismatch")
    if issues:
        return point_id, None, _unique_issues(issues)
    return point_id, VectorProjectionPointIdentity(chunk_id, point_id), ()


def _delete_completed(result: object) -> bool:
    status = getattr(result, "status", None)
    value = getattr(status, "value", status)
    return isinstance(value, str) and value.casefold() == "completed"


def _required_identity(value: object, name: str) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise ValueError(f"{name} must be a bounded non-blank identity")


def _unique_issues(issues: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(issues))


async def _close_client(client: object | None) -> None:
    if client is None:
        return
    close = getattr(client, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


__all__ = (
    "QdrantIdentityEvidence",
    "qdrant_point_id_for_chunk",
    "qdrant_target_commitment_sha256",
)
