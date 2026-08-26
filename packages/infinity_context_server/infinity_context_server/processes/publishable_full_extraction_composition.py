"""Resource-owning composition for one provider-neutral extraction worker."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    RuntimeReceiptVerificationPort,
)
from infinity_context_server.processes.publishable_full_extraction_worker import (
    OpenedPublishableExtractionStores,
    PublishableExtractionOneShotPort,
    PublishableExtractionRunAuthority,
    PublishableExtractionWorkerError,
    PublishableFullExtractionWorker,
)


def open_publishable_full_extraction_worker(
    *,
    authority: PublishableExtractionRunAuthority,
    stores_opener: Callable[[PublishableExtractionRunAuthority], OpenedPublishableExtractionStores],
    boundary: PublishableExtractionOneShotPort,
    runtime_receipt_verifier: RuntimeReceiptVerificationPort,
) -> PublishableFullExtractionWorker:
    """Open exact durable stores and close partial ownership on composition failure."""

    if not callable(stores_opener):
        raise PublishableExtractionWorkerError("extraction_stores_opener_invalid")
    stores: OpenedPublishableExtractionStores | None = None
    try:
        stores = stores_opener(authority)
        return PublishableFullExtractionWorker(
            authority=authority,
            stores=stores,
            boundary=boundary,
            runtime_receipt_verifier=runtime_receipt_verifier,
        )
    except BaseException:
        if stores is not None:
            with suppress(BaseException):
                stores.close()
        raise


__all__ = ("open_publishable_full_extraction_worker",)
