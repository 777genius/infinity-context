"""Small provider-neutral helpers for bounded retrieval-profile attestation."""

from __future__ import annotations

import hashlib
import json


def attestation_in_progress(exc: BaseException) -> bool:
    return str(exc) in {
        "retrieval_profile_attestation_incomplete",
        "retrieval_profile_attestation_deadline",
        "retrieval_profile_attestation_byte_budget",
        "retrieval_profile_attestation_cursor_raced",
        "retrieval_profile_attestation_page_raced",
        "retrieval_profile_provider_mutation_active",
    }


def attestation_page_evidence(start_cursor, end_cursor, rows) -> tuple[int, str]:
    canonical = json.dumps(
        {"end_cursor": end_cursor, "rows": rows, "start_cursor": start_cursor},
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(b"qdrant-attestation-page.v1\0" + canonical).hexdigest()
    return len(canonical), digest


def projection_item_manifest(items) -> list[list[object]]:
    return [
        [
            item.canonical_identity,
            item.canonical_version,
            item.canonical_watermark,
            item.payload_digest,
        ]
        for item in items
    ]


__all__ = (
    "attestation_in_progress",
    "attestation_page_evidence",
    "projection_item_manifest",
)
