"""Legacy /v1 digest API response shaping for the context_building seam."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Protocol

from infinity_context_server.features.context_building.legacy_api_responses import (
    LegacyContextApiResponseMapper,
)

_DIGEST_CONTRACT_DIAGNOSTIC_KEYS = (
    "evidence_only",
    "retrieval_disabled",
    "scope_not_found",
    "context_items_used",
    "pending_suggestions_considered",
    "superseded_facts_considered",
    "include_pending_suggestions",
    "include_superseded",
    "include_related",
    "dropped_by_char_cap",
    "truncated",
)


class NormalizeContextDiagnostics(Protocol):
    def __call__(self, diagnostics: object) -> dict[str, object]: ...


class SafePublicMetadata(Protocol):
    def __call__(self, metadata: Any, *, max_items: int = 120) -> dict[str, Any]: ...


class SafePublicText(Protocol):
    def __call__(self, value: str, *, limit: int = 500) -> str: ...


@dataclass(frozen=True, slots=True)
class LegacyDigestApiResponseMapper:
    """Build compatibility response payloads for legacy digest routes."""

    normalize_context_diagnostics: NormalizeContextDiagnostics
    safe_public_metadata: SafePublicMetadata
    safe_public_text: SafePublicText

    def digest_to_response(self, digest: object) -> dict[str, Any]:
        return {
            "digest_id": digest.digest_id,
            "topic": self.safe_public_text(digest.topic, limit=500),
            "rendered_markdown": self.safe_public_text(
                digest.rendered_markdown,
                limit=50000,
            ),
            "sections": [
                self.digest_section_to_response(section) for section in digest.sections
            ],
            "source_refs": [
                self.source_ref_to_response(ref) for ref in digest.source_refs
            ],
            "token_estimate": self.token_estimate_to_response(digest.token_estimate),
            "diagnostics": self.digest_diagnostics_to_response(digest.diagnostics),
        }

    def empty_digest_response(
        self,
        *,
        topic: str,
        policy_mode: str,
        request_id: str,
        scope_not_found: bool = False,
    ) -> dict[str, Any]:
        diagnostics: dict[str, object] = {
            "policy_mode": policy_mode,
            "retrieval_disabled": True,
            "evidence_only": True,
        }
        if scope_not_found:
            diagnostics = {
                "policy_mode": policy_mode,
                "scope_not_found": True,
                "retrieval_disabled": False,
                "evidence_only": True,
            }
        return {
            "meta": {"request_id": request_id},
            "data": {
                "digest_id": "dig_disabled"
                if not scope_not_found
                else "dig_scope_not_found",
                "topic": self.safe_public_text(topic, limit=500),
                "rendered_markdown": "",
                "sections": [],
                "source_refs": [],
                "token_estimate": self.token_estimate_to_response(0),
                "diagnostics": self.digest_diagnostics_to_response(diagnostics),
            },
        }

    def digest_section_to_response(self, section: object) -> dict[str, Any]:
        return {
            "title": self.safe_public_text(section.title, limit=240),
            "items": [
                self.context_item_to_response(item) for item in section.items
            ],
            "truncated": section.truncated,
        }

    def context_item_to_response(self, item: object) -> dict[str, Any]:
        return self._context_response_mapper().context_item_to_response(item)

    def source_ref_to_response(self, ref: object) -> dict[str, Any]:
        quote_preview = getattr(ref, "quote_preview", None)
        char_start, char_end = _range_pair(
            getattr(ref, "char_start", None),
            getattr(ref, "char_end", None),
        )
        time_start_ms, time_end_ms = _range_pair(
            getattr(ref, "time_start_ms", None),
            getattr(ref, "time_end_ms", None),
        )
        return {
            "source_type": self.safe_public_text(
                str(getattr(ref, "source_type", "")),
                limit=80,
            ),
            "source_id": self.safe_public_text(
                str(getattr(ref, "source_id", "")),
                limit=160,
            ),
            "chunk_id": self._optional_public_text(
                getattr(ref, "chunk_id", None),
                limit=160,
            ),
            "char_start": char_start,
            "char_end": char_end,
            "quote_preview": (
                self.safe_public_text(quote_preview) if quote_preview else None
            ),
            "page_number": _positive_int(getattr(ref, "page_number", None)),
            "time_start_ms": time_start_ms,
            "time_end_ms": time_end_ms,
            "bbox": _bbox_to_response(getattr(ref, "bbox", None)),
        }

    def token_estimate_to_response(self, token_estimate: object) -> object:
        return token_estimate

    def digest_diagnostics_to_response(self, diagnostics: object) -> dict[str, Any]:
        response = self.safe_public_metadata(diagnostics)
        if not isinstance(diagnostics, dict):
            return response
        for key in _DIGEST_CONTRACT_DIAGNOSTIC_KEYS:
            if key not in diagnostics:
                continue
            safe_value = self.safe_public_metadata({key: diagnostics[key]}, max_items=1)
            if key in safe_value:
                response[key] = safe_value[key]
        return response

    def _context_response_mapper(self) -> LegacyContextApiResponseMapper:
        return LegacyContextApiResponseMapper(
            normalize_context_diagnostics=self.normalize_context_diagnostics,
            normalize_context_bundle_diagnostics=_unused_context_bundle_diagnostics,
            safe_public_metadata=self.safe_public_metadata,
            safe_public_text=self.safe_public_text,
            source_ref_to_response=self.source_ref_to_response,
        )

    def _optional_public_text(self, value: object, *, limit: int) -> str | None:
        if value is None:
            return None
        text = self.safe_public_text(str(value), limit=limit).strip()
        return text or None


def _unused_context_bundle_diagnostics(
    diagnostics: dict[str, Any],
    *,
    items: object,
) -> dict[str, object]:
    del items
    return dict(diagnostics) if isinstance(diagnostics, dict) else {}


def _range_pair(start: object, end: object) -> tuple[int | None, int | None]:
    parsed_start = _non_negative_int(start)
    parsed_end = _non_negative_int(end)
    if (start is not None and parsed_start is None) or (
        end is not None and parsed_end is None
    ):
        return None, None
    if parsed_start is not None and parsed_end is not None and parsed_end < parsed_start:
        return None, None
    return parsed_start, parsed_end


def _positive_int(value: object) -> int | None:
    parsed = _non_negative_int(value)
    return parsed if parsed is not None and parsed >= 1 else None


def _non_negative_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _bbox_to_response(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        bbox = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not all(isfinite(item) for item in bbox):
        return None
    if any(item < 0 for item in bbox) or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return bbox
