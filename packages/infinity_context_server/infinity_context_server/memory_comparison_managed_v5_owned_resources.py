"""Idempotent reverse-order ownership for managed-v5 runtime resources."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import final


class ManagedV5OwnedResourcesError(RuntimeError):
    """Stable close failure which never reflects provider or credential data."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedV5OwnedResources:
    """Close runtime-owned handles once, in reverse construction order.

    Cleanup is deliberately absent: benchmark cleanup remains lifecycle/policy
    work and must complete before this low-level resource owner is closed.
    """

    __slots__ = ("_closed", "_lock", "_resources")

    def __init__(self, resources: Iterable[object] = ()) -> None:
        try:
            captured = tuple(resources)
        except Exception:
            raise ManagedV5OwnedResourcesError("managed_v5_owned_resources_invalid") from None
        if any(not callable(getattr(item, "close", None)) for item in captured):
            raise ManagedV5OwnedResourcesError("managed_v5_owned_resources_invalid")
        if len({id(item) for item in captured}) != len(captured):
            raise ManagedV5OwnedResourcesError("managed_v5_owned_resources_invalid")
        self._resources = captured
        self._closed = False
        self._lock = threading.RLock()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def _register(self, resource: object) -> object:
        """Register one lazily-created owned handle for the composition root."""

        if not callable(getattr(resource, "close", None)):
            raise ManagedV5OwnedResourcesError("managed_v5_owned_resources_invalid")
        with self._lock:
            if self._closed or any(item is resource for item in self._resources):
                raise ManagedV5OwnedResourcesError("managed_v5_owned_resources_invalid")
            self._resources = (*self._resources, resource)
        return resource

    def close(self) -> None:
        """Close every resource at most once, continuing after individual failures."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            resources = self._resources
            self._resources = ()
        failed = False
        for resource in reversed(resources):
            try:
                resource.close()
                if getattr(resource, "close_warning_code", None) is not None:
                    failed = True
            except BaseException as error:
                if not isinstance(error, Exception):
                    raise
                failed = True
        if failed:
            raise ManagedV5OwnedResourcesError("managed_v5_owned_resources_close_failed")

    def __enter__(self) -> ManagedV5OwnedResources:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ("ManagedV5OwnedResources", "ManagedV5OwnedResourcesError")
