"""Pinned Mem0 OSS SDK adapter with no ambient provider credential fallback."""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from mem0_oss_adapter.port import OssPort, UnconfiguredOssPort
from mem0_oss_adapter.residue import (
    ResidueCleanupError,
    prepare_scope_ledger,
    purge_scope_residue,
    purge_source_residue,
    record_scope_memory_ids,
    require_isolated_subscription_scope,
    scope_ledger_memory_ids,
    snapshot_history_memory_ids,
    snapshot_scope_memory_ids,
    snapshot_source_memory_ids,
    source_ledger_memory_ids,
)
from mem0_oss_adapter.runtime_pin import RUNTIME_PIN
from mem0_oss_adapter.subscription_llm import (
    SubscriptionBridgeConfig,
    SubscriptionOpenAICompatibleLlm,
    UsageLedger,
    validate_loopback_bridge_url,
)
from mem0_oss_adapter.usage import RunUsageAggregate

_Mode = Literal["raw_passthrough", "subscription_llm"]
_FACTORY_LOCK = threading.RLock()
_AMBIENT_PROVIDER_KEYS = (
    "MEM0_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENROUTER_API_KEY",
    "MEMORY_OPENAI_API_KEY",
)
_SAFE_COLLECTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")


@dataclass(frozen=True, slots=True)
class OssRuntimeSettings:
    qdrant_host: str
    qdrant_port: int
    collection_name: str
    state_dir: Path
    model_dir: Path
    extraction_mode: _Mode
    bridge_url: str | None
    bearer_token: str | None
    request_max_bytes: int = 65_536
    response_max_bytes: int = 65_536

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> OssRuntimeSettings | None:
        env = os.environ if environment is None else environment
        host = _nonempty(env.get("MEM0_OSS_QDRANT_HOST"))
        model_dir = _nonempty(env.get("MEM0_OSS_FASTEMBED_MODEL_DIR"))
        if host is None or model_dir is None:
            return None
        if host != "qdrant" and not _is_loopback_ip(host):
            raise ValueError("Qdrant host must be the local qdrant service or a loopback address")
        port = _bounded_port(env.get("MEM0_OSS_QDRANT_PORT", "6333"))
        collection = env.get("MEM0_OSS_COLLECTION", "mem0_oss_benchmark")
        if not _SAFE_COLLECTION.fullmatch(collection):
            raise ValueError("Mem0 OSS collection name is invalid")
        state_dir = Path(env.get("MEM0_OSS_STATE_DIR", "/var/lib/mem0-oss"))
        if not state_dir.is_absolute():
            raise ValueError("Mem0 OSS state directory must be absolute")
        mode = env.get("MEM0_OSS_EXTRACTION_MODE", "raw_passthrough")
        if mode not in {"raw_passthrough", "subscription_llm"}:
            raise ValueError("Mem0 OSS extraction mode is invalid")
        bridge_url: str | None = None
        bearer_token: str | None = None
        if mode == "subscription_llm":
            bridge_url = validate_loopback_bridge_url(env.get("MEM0_OSS_SUBSCRIPTION_BRIDGE_URL"))
            bearer_token = _nonempty(env.get("MEM0_OSS_SUBSCRIPTION_BEARER_TOKEN"))
            if bearer_token is None or bearer_token != env.get(
                "MEM0_OSS_SUBSCRIPTION_BEARER_TOKEN"
            ):
                raise ValueError("Mem0 OSS subscription bearer token is invalid")
        return cls(
            qdrant_host=host,
            qdrant_port=port,
            collection_name=collection,
            state_dir=state_dir,
            model_dir=Path(model_dir),
            extraction_mode=mode,
            bridge_url=bridge_url,
            bearer_token=bearer_token,
        )


class OfflineQdrantStore:
    """Real Mem0 Qdrant storage with the optional network-downloading BM25 disabled."""

    def __new__(cls, **config: Any) -> Any:
        from mem0.vector_stores.qdrant import Qdrant

        class _PinnedQdrant(Qdrant):
            def _get_bm25_encoder(self) -> None:
                return None

            def keyword_search(self, *args: Any, **kwargs: Any) -> None:
                del args, kwargs
                return None

        return _PinnedQdrant(**config)


class Mem0OssSdkPort:
    """Adapter that turns the SDK's unsupported OSS timestamp into explicit metadata."""

    def __init__(
        self,
        *,
        settings: OssRuntimeSettings,
        memory_factory: Any | None = None,
    ) -> None:
        self._settings = settings
        self._memory_factory = memory_factory
        self._memory: Any | None = None
        self._memory_lock = threading.Lock()
        self._operation_lock = threading.RLock()
        self._ledger = UsageLedger()
        self._last_sdk_timestamp: int | None = None

    @property
    def configured(self) -> bool:
        return True

    @property
    def extraction_mode(self) -> _Mode:
        return self._settings.extraction_mode

    @property
    def usage_ledger(self) -> UsageLedger:
        return self._ledger

    @property
    def last_sdk_timestamp(self) -> int | None:
        """Testing-only observable proof that the OSS SDK receives `None`."""

        return self._last_sdk_timestamp

    def add(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        user_id: str,
        agent_id: str | None,
        run_id: str,
        metadata: Mapping[str, Any],
        timestamp: int,
        mode_override: _Mode | None = None,
    ) -> Mapping[str, Any]:
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ValueError("benchmark timestamp must be a non-negative integer")
        mode = mode_override or self._settings.extraction_mode
        if mode not in {"raw_passthrough", "subscription_llm"}:
            raise ValueError("Mem0 OSS extraction mode is invalid")
        metadata_to_persist = dict(metadata)
        created_at = _timestamp_created_at(timestamp)
        existing_created_at = metadata_to_persist.get("created_at")
        if existing_created_at is not None and existing_created_at != created_at:
            raise ValueError("metadata.created_at conflicts with the benchmark timestamp")
        metadata_to_persist["created_at"] = created_at
        source_id = _required_metadata_text(metadata_to_persist, "source_id")
        source_sha256 = _required_metadata_text(metadata_to_persist, "source_sha256")
        max_calls = 1 if mode == "subscription_llm" else 0
        with self._operation_lock:
            memory = self._ensure_memory()
            prepare_scope_ledger(memory.db)
            if mode == "subscription_llm":
                require_isolated_subscription_scope(
                    memory,
                    user_id=user_id,
                    run_id=run_id,
                )
            before_vector_ids = set(
                snapshot_scope_memory_ids(memory, user_id=user_id, run_id=run_id)
            )
            before_history_ids = set(snapshot_history_memory_ids(memory.db))
            try:
                with self._ledger.operation(
                    run_id=run_id,
                    mode=mode,
                    max_calls=max_calls,
                    request_max_bytes=self._settings.request_max_bytes,
                    response_max_bytes=self._settings.response_max_bytes,
                ):
                    self._last_sdk_timestamp = None
                    result = memory.add(
                        [dict(message) for message in messages],
                        user_id=user_id,
                        agent_id=agent_id,
                        run_id=run_id,
                        metadata=metadata_to_persist,
                        timestamp=None,
                        infer=mode == "subscription_llm",
                    )
            finally:
                after_vector_ids = set(
                    snapshot_scope_memory_ids(memory, user_id=user_id, run_id=run_id)
                )
                after_history_ids = set(snapshot_history_memory_ids(memory.db))
                new_vector_ids = after_vector_ids - before_vector_ids
                new_history_ids = after_history_ids - before_history_ids
                new_state_ids = tuple(sorted(new_vector_ids | new_history_ids))
                if new_state_ids:
                    record_scope_memory_ids(
                        memory.db,
                        memory_ids=new_state_ids,
                        user_id=user_id,
                        run_id=run_id,
                        source_id=source_id,
                        source_sha256=source_sha256,
                    )
            if not isinstance(result, Mapping):
                raise RuntimeError("Mem0 OSS add returned an invalid payload")
            created_ids = set(_sdk_created_memory_ids(result))
            if created_ids != set(new_state_ids) or created_ids != new_history_ids:
                raise RuntimeError("Mem0 OSS add result differs from newly persisted state")
        return result

    def get_all(self, *, filters: Mapping[str, Any], limit: int) -> Mapping[str, Any]:
        if not 1 <= limit <= 1000:
            raise ValueError("Mem0 OSS readback limit is invalid")
        with self._operation_lock:
            result = self._ensure_memory().get_all(filters=dict(filters), top_k=limit)
        if not isinstance(result, Mapping):
            raise RuntimeError("Mem0 OSS readback returned an invalid payload")
        return result

    def search(
        self,
        *,
        query: str,
        filters: Mapping[str, Any],
        top_k: int,
    ) -> Mapping[str, Any]:
        if not 1 <= top_k <= 1000:
            raise ValueError("Mem0 OSS search limit is invalid")
        with self._operation_lock:
            result = self._ensure_memory().search(query, filters=dict(filters), top_k=top_k)
        if not isinstance(result, Mapping):
            raise RuntimeError("Mem0 OSS search returned an invalid payload")
        return result

    def usage_for_run(self, *, run_id: str) -> RunUsageAggregate:
        with self._operation_lock:
            return self._ledger.aggregate_for_run(run_id=run_id)

    def delete_memories(self, *, user_id: str, run_id: str) -> bool:
        with self._operation_lock:
            memory = self._ensure_memory()
            live_ids = snapshot_scope_memory_ids(memory, user_id=user_id, run_id=run_id)
            ledger_ids = scope_ledger_memory_ids(memory.db, user_id=user_id, run_id=run_id)
            if not set(live_ids).issubset(ledger_ids):
                raise ResidueCleanupError("live scope ids are absent from the canonical ledger")
            memory.delete_all(user_id=user_id, run_id=run_id)
            purge_scope_residue(
                memory,
                memory_ids=ledger_ids,
                user_id=user_id,
                run_id=run_id,
            )
            if snapshot_scope_memory_ids(memory, user_id=user_id, run_id=run_id):
                raise ResidueCleanupError("vector residue remains after exact-scope purge")
        return True

    def delete_source_memories(
        self,
        *,
        user_id: str,
        run_id: str,
        source_id: str,
        source_sha256: str,
    ) -> bool:
        with self._operation_lock:
            memory = self._ensure_memory()
            scope_live_ids = set(snapshot_scope_memory_ids(memory, user_id=user_id, run_id=run_id))
            live_ids = snapshot_source_memory_ids(
                memory,
                user_id=user_id,
                run_id=run_id,
                source_id=source_id,
                source_sha256=source_sha256,
            )
            if live_ids:
                record_scope_memory_ids(
                    memory.db,
                    memory_ids=live_ids,
                    user_id=user_id,
                    run_id=run_id,
                    source_id=source_id,
                    source_sha256=source_sha256,
                )
            ledger_ids = source_ledger_memory_ids(
                memory.db,
                user_id=user_id,
                run_id=run_id,
                source_id=source_id,
                source_sha256=source_sha256,
            )
            if not set(live_ids).issubset(ledger_ids):
                raise ResidueCleanupError("live source ids are absent from the canonical ledger")
            for memory_id in ledger_ids:
                if memory_id not in scope_live_ids:
                    continue
                memory.delete(memory_id)
            purge_source_residue(
                memory,
                memory_ids=ledger_ids,
                user_id=user_id,
                run_id=run_id,
                source_id=source_id,
                source_sha256=source_sha256,
            )
            if snapshot_source_memory_ids(
                memory,
                user_id=user_id,
                run_id=run_id,
                source_id=source_id,
                source_sha256=source_sha256,
            ):
                raise ResidueCleanupError("vector residue remains after exact-source purge")
            remaining_scope_ids = set(
                snapshot_scope_memory_ids(memory, user_id=user_id, run_id=run_id)
            )
            if remaining_scope_ids.intersection(ledger_ids):
                raise ResidueCleanupError("source vector ids remain after ledger purge")
        return True

    def close(self) -> None:
        if self._memory is None:
            return
        llm = getattr(self._memory, "llm", None)
        if isinstance(llm, SubscriptionOpenAICompatibleLlm):
            llm.close()

    def _ensure_memory(self) -> Any:
        if self._memory is not None:
            return self._memory
        with self._memory_lock:
            if self._memory is not None:
                return self._memory
            _neutralize_ambient_provider_environment()
            self._settings.state_dir.mkdir(parents=True, exist_ok=True)
            if self._memory_factory is not None:
                self._memory = self._memory_factory()
                return self._memory
            self._memory = self._build_pinned_memory()
            return self._memory

    def _build_pinned_memory(self) -> Any:
        from mem0 import Memory

        config = pinned_memory_config(self._settings, usage_ledger=self._ledger)
        with _patched_mem0_factories():
            return Memory.from_config(config)


def oss_from_environment() -> OssPort:
    settings = OssRuntimeSettings.from_environment()
    return UnconfiguredOssPort() if settings is None else Mem0OssSdkPort(settings=settings)


def pinned_memory_config(
    settings: OssRuntimeSettings,
    *,
    usage_ledger: UsageLedger,
) -> dict[str, Any]:
    """Build the one narrow Mem0 configuration accepted by the immutable runtime."""

    return {
        "version": "v1.1",
        "history_db_path": str(settings.state_dir / "history.db"),
        "llm": {
            "provider": "openai",
            "config": {
                "bridge_url": settings.bridge_url,
                "bearer_token": settings.bearer_token,
                "mode": settings.extraction_mode,
                "usage_ledger": usage_ledger,
                "request_max_bytes": settings.request_max_bytes,
                "response_max_bytes": settings.response_max_bytes,
                "model": "gpt-5.6-sol",
                "max_tokens": 512,
            },
        },
        "embedder": {
            "provider": "fastembed",
            "config": {
                "model": RUNTIME_PIN.embedding_model,
                "embedding_dims": 384,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": settings.qdrant_host,
                "port": settings.qdrant_port,
                "path": None,
                "collection_name": settings.collection_name,
                "embedding_model_dims": 384,
                "on_disk": True,
            },
        },
    }


@contextmanager
def _patched_mem0_factories():
    """Patch only construction-time factory entries, then restore the global registry."""

    from mem0.utils.factory import EmbedderFactory, LlmFactory, VectorStoreFactory

    with _FACTORY_LOCK:
        old_llm = LlmFactory.provider_to_class["openai"]
        old_embedder = EmbedderFactory.provider_to_class["fastembed"]
        old_vector = VectorStoreFactory.provider_to_class["qdrant"]
        LlmFactory.provider_to_class["openai"] = (
            "mem0_oss_adapter.subscription_llm.SubscriptionOpenAICompatibleLlm",
            SubscriptionBridgeConfig,
        )
        EmbedderFactory.provider_to_class["fastembed"] = (
            "mem0_oss_adapter.embedding.OfflineFastEmbedEmbedding"
        )
        VectorStoreFactory.provider_to_class["qdrant"] = (
            "mem0_oss_adapter.sdk_oss.OfflineQdrantStore"
        )
        try:
            yield
        finally:
            LlmFactory.provider_to_class["openai"] = old_llm
            EmbedderFactory.provider_to_class["fastembed"] = old_embedder
            VectorStoreFactory.provider_to_class["qdrant"] = old_vector


def _neutralize_ambient_provider_environment() -> None:
    """The adapter's process never permits provider credentials to influence the SDK."""

    for key in _AMBIENT_PROVIDER_KEYS:
        os.environ.pop(key, None)
    os.environ["MEM0_TELEMETRY"] = "false"
    os.environ["MEM0_TELEMETRY_SAMPLE_RATE"] = "0"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


def _nonempty(value: object) -> str | None:
    return value if isinstance(value, str) and value and value == value.strip() else None


def _bounded_port(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Qdrant port is invalid") from exc
    if not 1 <= parsed <= 65_535:
        raise ValueError("Qdrant port is invalid")
    return parsed


def _is_loopback_ip(value: str) -> bool:
    import ipaddress

    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _timestamp_created_at(timestamp: int) -> str:
    value = datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")
    return value.replace("+00:00", "Z")


def _sdk_created_memory_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    results = payload.get("results")
    if not isinstance(results, Sequence) or isinstance(results, str | bytes):
        raise RuntimeError("Mem0 OSS add returned no result list")
    ids = tuple(item.get("id") if isinstance(item, Mapping) else None for item in results)
    if not ids or any(not isinstance(memory_id, str) or not memory_id for memory_id in ids):
        raise RuntimeError("Mem0 OSS add returned invalid memory ids")
    if len(ids) != len(set(ids)):
        raise RuntimeError("Mem0 OSS add returned duplicate memory ids")
    return ids


def _required_metadata_text(metadata: Mapping[str, Any], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Mem0 OSS metadata.{key} is invalid")
    return value
