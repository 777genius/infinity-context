from __future__ import annotations

from infinity_context_core.application.context_ranked_evidence_coverage_reservation import (
    reserve_paired_evidence_head,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_STATE_QUERY = (
    "For the coffee-to-water ratio in my French press, did I switch to more water per "
    "tablespoon of coffee, or less?"
)


def test_source_dated_ratio_measurements_reserve_both_state_roles() -> None:
    earlier = _ratio_item(
        "six-ounces",
        "I use 1 tablespoon of coffee for every 6 ounces of water.",
        "conversation:ratio-notes:session-01",
        source_header="session-01 date: 2023/02/11",
    )
    later = _ratio_item(
        "five-ounces",
        "I use 1 tablespoon of coffee for every 5 ounces of water.",
        "conversation:ratio-notes:session-02",
        source_header="session-02 date: 2023/06/30",
    )

    reservation = _reserve((earlier, later))

    assert [item.item_id for item in reservation.items[:2]] == [
        "six-ounces",
        "five-ounces",
    ]
    assert reservation.reservation_count == 2


def test_explicit_state_labels_reserve_without_source_dates() -> None:
    earlier = _ratio_item(
        "previous",
        "Previously I used 1 tablespoon of coffee per 6 ounces of water.",
        "conversation:ratio-notes:early",
    )
    later = _ratio_item(
        "current",
        "I now use 1 tablespoon of coffee per 5 ounces of water.",
        "conversation:ratio-notes:current",
    )

    reservation = _reserve((earlier, later))

    assert [item.item_id for item in reservation.items[:2]] == ["previous", "current"]
    assert reservation.reservation_count == 2


def test_latest_stale_measurement_cannot_complete_current_state_role() -> None:
    earlier = _ratio_item(
        "earlier",
        "I use 1 tablespoon of coffee per 6 ounces of water.",
        "conversation:ratio-notes:session-03",
        source_header="session-03 date: 2023/02/11",
    )
    latest_stale = _ratio_item(
        "latest-stale",
        "I use 1 tablespoon of coffee per 5 ounces of water.",
        "conversation:ratio-notes:session-04",
        source_header="session-04 date: 2023/06/30",
        diagnostics={"fact_status": "stale"},
    )

    reservation = _reserve((earlier, latest_stale))

    assert reservation.reservation_count < 2


def _reserve(items: tuple[ContextItem, ...]):
    return reserve_paired_evidence_head(
        items,
        query=_STATE_QUERY,
        max_items=10,
        max_tokens=10_000,
        max_chars=100_000,
    )


def _ratio_item(
    item_id: str,
    text: str,
    source_id: str,
    *,
    source_header: str | None = None,
    diagnostics: dict[str, object] | None = None,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="conversation",
                source_id=source_id,
                quote_preview=source_header,
            ),
        ),
        diagnostics=diagnostics,
    )
