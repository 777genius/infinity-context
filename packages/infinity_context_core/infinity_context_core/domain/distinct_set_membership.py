"""Pure bounded reservation policy for distinct-set member evidence."""

from __future__ import annotations

from dataclasses import dataclass

_MAX_MEMBER_IDS_PER_CANDIDATE = 12


@dataclass(frozen=True)
class DistinctSetMemberCandidate:
    """Provider-neutral evidence contribution from one canonical source family."""

    candidate_id: str
    source_family: str
    member_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("distinct-set candidate_id is required")
        if not self.source_family.strip():
            raise ValueError("distinct-set source_family is required")
        if not self.member_ids:
            raise ValueError("distinct-set member_ids are required")
        if len(self.member_ids) > _MAX_MEMBER_IDS_PER_CANDIDATE:
            raise ValueError("distinct-set member_ids exceed bounded maximum")
        if any(not value.strip() for value in self.member_ids):
            raise ValueError("distinct-set member_ids cannot be blank")
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("distinct-set member_ids must be unique")


@dataclass(frozen=True)
class DistinctSetMemberReservation:
    selected_ids: tuple[str, ...]
    reserved_member_ids: tuple[str, ...]


class DistinctSetMemberReservationPolicy:
    """Reserve source-backed candidates only when they add a target member."""

    def select(
        self,
        candidates: tuple[DistinctSetMemberCandidate, ...],
        *,
        limit: int,
    ) -> DistinctSetMemberReservation:
        if limit <= 0:
            return DistinctSetMemberReservation((), ())
        selected: list[str] = []
        covered_members: set[str] = set()
        used_sources: set[str] = set()
        for candidate in candidates:
            if candidate.source_family in used_sources:
                continue
            novel_members = tuple(
                member_id for member_id in candidate.member_ids if member_id not in covered_members
            )
            if not novel_members:
                continue
            selected.append(candidate.candidate_id)
            used_sources.add(candidate.source_family)
            covered_members.update(novel_members)
            if len(selected) >= limit:
                break
        return DistinctSetMemberReservation(
            selected_ids=tuple(selected),
            reserved_member_ids=tuple(sorted(covered_members)),
        )
