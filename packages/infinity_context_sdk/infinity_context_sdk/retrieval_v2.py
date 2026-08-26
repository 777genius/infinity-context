"""Strict official Python HTTP client surface for locator-only Retrieval V2."""

from __future__ import annotations

import asyncio
import json
import time
from threading import Event

import httpx
from infinity_context_contracts.features.context_building import (
    CONTEXT_RETRIEVAL_ERROR_SPECS_V2,
    ContextRetrievalV2ErrorEnvelopeDto,
    RetrievalV2CapabilityDto,
    RetrieveContextV2RequestDto,
    RetrieveContextV2ResponseDto,
    decode_context_retrieval_v2_json,
    decode_retrieve_context_v2_response,
)

from infinity_context_sdk.async_facade import run_on_owned_loop
from infinity_context_sdk.errors import InfinityContextError


class InfinityContextRetrievalV2Error(InfinityContextError):
    """A canonical Retrieval V2 error envelope or strict client-side rejection."""


class InfinityContextRetrievalV2ContractError(InfinityContextRetrievalV2Error):
    """The request, attestation, or response violated the canonical contract."""


class InfinityContextRetrievalV2Mixin:
    base_url: str
    token: str | None
    timeout: float
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None
    async_transport: httpx.AsyncBaseTransport | None

    def retrieve_context_v2(
        self,
        request: RetrieveContextV2RequestDto,
        *,
        capability: RetrievalV2CapabilityDto,
        cancellation_event: Event | None = None,
    ) -> RetrieveContextV2ResponseDto:
        """Execute on an owned async loop so cancellation aborts the HTTP exchange."""
        request_budget = (
            request.bounds.deadline_ms / 1000
            if isinstance(request, RetrieveContextV2RequestDto)
            else self.timeout
        )
        transport = self._cancellable_async_transport()
        return run_on_owned_loop(
            lambda: self._retrieve_context_v2_async(
                request,
                capability=capability,
                cancellation_event=cancellation_event,
                deadline=time.monotonic() + min(self.timeout, request_budget),
                transport=transport,
            )
        )

    async def _retrieve_context_v2_async(
        self,
        request: RetrieveContextV2RequestDto,
        *,
        capability: RetrievalV2CapabilityDto,
        cancellation_event: Event | None,
        deadline: float,
        transport: httpx.AsyncBaseTransport | None,
    ) -> RetrieveContextV2ResponseDto:
        """Run one cancellable exchange and await all cancellation cleanup."""

        try:
            _check_budget(deadline, cancellation_event)
            if not isinstance(request, RetrieveContextV2RequestDto):
                raise ValueError("request must be RetrieveContextV2RequestDto")
            if not isinstance(capability, RetrievalV2CapabilityDto):
                raise ValueError("capability must be RetrievalV2CapabilityDto")
            canonical_request = RetrieveContextV2RequestDto.from_dict(request.to_dict())
            canonical_capability = RetrievalV2CapabilityDto.from_dict(capability.to_dict())
            if (
                canonical_request.capability_fingerprint
                != canonical_capability.capability_fingerprint
                or canonical_request.profile_id != canonical_capability.profile_id
            ):
                raise ValueError("request capability/profile does not match attestation")
            payload = json.dumps(
                canonical_request.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            _check_budget(deadline, cancellation_event)
        except (TypeError, ValueError, UnicodeError) as exc:
            raise _contract_error(str(exc)) from exc

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        maximum_bytes = canonical_request.bounds.response_byte_limit
        transport_timeout = _remaining(deadline, cancellation_event)
        async with httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            timeout=transport_timeout,
            headers=headers,
            transport=transport,
        ) as client:
            try:
                async with asyncio.timeout(_remaining(deadline, cancellation_event)):
                    response, body = await _race_response(
                        client, payload, maximum_bytes, cancellation_event
                    )
            except InfinityContextRetrievalV2Error:
                raise
            except TimeoutError as exc:
                raise InfinityContextRetrievalV2Error(
                    status_code=0,
                    code="memory.context_retrieval_deadline_exceeded",
                    message="Retrieval V2 request exceeded its absolute deadline",
                    retryable=True,
                    unknown_commit_state=False,
                ) from exc
            except httpx.TimeoutException as exc:
                raise InfinityContextRetrievalV2Error(
                    status_code=0,
                    code="memory.context_retrieval_deadline_exceeded",
                    message="Retrieval V2 request did not complete within its transport bound",
                    retryable=True,
                    unknown_commit_state=False,
                ) from exc
            except (httpx.NetworkError, httpx.TransportError) as exc:
                raise InfinityContextRetrievalV2Error(
                    status_code=0,
                    code="memory.context_retrieval_unavailable",
                    message="Retrieval V2 transport is unavailable",
                    retryable=True,
                    unknown_commit_state=False,
                ) from exc

        if response.is_error:
            raise _decode_error(response.status_code, body)
        try:
            _check_budget(deadline, cancellation_event)
            result = decode_retrieve_context_v2_response(body)
            _check_budget(deadline, cancellation_event)
            if (
                result.capability_fingerprint != canonical_request.capability_fingerprint
                or result.capability_fingerprint != canonical_capability.capability_fingerprint
                or result.profile_id != canonical_request.profile_id
                or result.profile_id != canonical_capability.profile_id
            ):
                raise ValueError("response capability/profile does not match attestation")
            applied = result.applied_bounds
            requested = canonical_request.bounds
            if (
                applied.candidate_limit != requested.candidate_limit
                or applied.result_limit != requested.result_limit
                or applied.neighbor_radius != requested.neighbor_radius
                or applied.response_byte_limit != requested.response_byte_limit
                or applied.deadline_ms != requested.deadline_ms
            ):
                raise ValueError("response applied bounds do not match request")
            _validate_cross_envelope(
                result.to_dict(),
                canonical_request.to_dict(),
                canonical_capability.to_dict(),
                received_bytes=len(body),
            )
            _check_budget(deadline, cancellation_event)
            return result
        except (TypeError, ValueError, UnicodeError) as exc:
            raise _contract_error(str(exc), status_code=response.status_code) from exc


async def _read_response(
    client: httpx.AsyncClient, payload: bytes, maximum_bytes: int
) -> tuple[httpx.Response, bytes]:
    async with client.stream("POST", "/v1/context/retrieve", content=payload) as response:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > maximum_bytes:
                raise _contract_error("Retrieval V2 response exceeded byte limit")
        return response, bytes(body)


async def _race_response(client, payload, maximum_bytes, cancellation_event):
    request_task = asyncio.create_task(
        _read_response(client, payload, maximum_bytes), name="infinity-retrieval-v2-http"
    )
    cancellation_task = asyncio.create_task(
        _wait_for_cancellation(cancellation_event),
        name="infinity-retrieval-v2-cancellation",
    )
    try:
        done, _ = await asyncio.wait(
            (request_task, cancellation_task), return_when=asyncio.FIRST_COMPLETED
        )
        if cancellation_task in done and cancellation_task.result():
            raise _cancelled_error()
        return await request_task
    finally:
        for task in (request_task, cancellation_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(request_task, cancellation_task, return_exceptions=True)


async def _wait_for_cancellation(cancellation_event: Event | None) -> bool:
    if cancellation_event is None:
        await asyncio.Future()
    while not cancellation_event.is_set():
        await asyncio.sleep(0.005)
    return True


def _cancelled_error() -> InfinityContextRetrievalV2Error:
    return InfinityContextRetrievalV2Error(
        status_code=0,
        code="memory.context_retrieval_cancelled",
        message="Retrieval V2 request was cancelled",
        retryable=False,
        unknown_commit_state=False,
    )


def _decode_error(status_code: int, body: bytes) -> InfinityContextRetrievalV2Error:
    try:
        decoded = decode_context_retrieval_v2_json(body)
        if not isinstance(decoded, dict):
            raise ValueError("error envelope must be an object")
        envelope = ContextRetrievalV2ErrorEnvelopeDto.from_dict(decoded)
        if envelope.http_status != status_code:
            raise ValueError("HTTP status does not match Retrieval V2 error code")
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError) as exc:
        raise _contract_error(
            "Retrieval V2 returned an invalid error envelope", status_code
        ) from exc
    return InfinityContextRetrievalV2Error(
        status_code=status_code,
        code=envelope.error.code,
        message=envelope.error.message,
        retryable=envelope.error.retryable,
        unknown_commit_state=False,
    )


def _contract_error(message: str, status_code: int = 0):
    spec = CONTEXT_RETRIEVAL_ERROR_SPECS_V2["memory.context_retrieval_contract_invalid"]
    return InfinityContextRetrievalV2ContractError(
        status_code=status_code,
        code="memory.context_retrieval_contract_invalid",
        message=message or "Retrieval V2 contract is invalid",
        retryable=spec[1],
        unknown_commit_state=False,
    )


def _remaining(deadline: float, cancellation_event: Event | None) -> float:
    _check_budget(deadline, cancellation_event)
    return max(deadline - time.monotonic(), 0.000_001)


def _check_budget(deadline: float, cancellation_event: Event | None) -> None:
    if cancellation_event is not None and cancellation_event.is_set():
        raise InfinityContextRetrievalV2Error(
            status_code=0,
            code="memory.context_retrieval_cancelled",
            message="Retrieval V2 request was cancelled",
            retryable=False,
            unknown_commit_state=False,
        )
    if time.monotonic() >= deadline:
        raise InfinityContextRetrievalV2Error(
            status_code=0,
            code="memory.context_retrieval_deadline_exceeded",
            message="Retrieval V2 request exceeded its absolute deadline",
            retryable=True,
            unknown_commit_state=False,
        )


def _validate_cross_envelope(response, request, capability, *, received_bytes: int) -> None:
    bounds = response["applied_bounds"]
    candidates = response["candidates"]
    outcomes = response["provider_outcomes"]
    reasons = response["degradation_reason_codes"]
    if received_bytes > bounds["response_byte_limit"]:
        raise ValueError("response exceeds requested byte limit")
    if len(candidates) != bounds["returned_seeds"] or len(candidates) > bounds["result_limit"]:
        raise ValueError("response candidate count differs from applied bounds")
    if (response["status"] == "available") != bool(candidates):
        raise ValueError("response status differs from candidate availability")
    lanes = {item["provider_id"]: item for item in capability["provider_lanes"]}
    outcome_by_provider = {item["provider_id"]: item for item in outcomes}
    if len(outcome_by_provider) != len(outcomes):
        raise ValueError("provider outcomes must be unique")
    pre_provider = len(reasons) == 1 and reasons[0] in {
        "capability_profile_mismatch",
        "neighbor_capability_unavailable",
    }
    if not pre_provider and tuple(outcome_by_provider) != tuple(lanes):
        raise ValueError("provider outcomes must cover attested lanes")
    failed_required = [
        lane_id
        for lane_id in capability["required_provider_lanes"]
        if lane_id not in outcome_by_provider
        or outcome_by_provider[lane_id]["status"] != "available"
        or outcome_by_provider[lane_id]["reason_code"] is not None
    ]
    if failed_required and (candidates or response["status"] != "unavailable"):
        raise ValueError("failed required provider lane must fail closed")
    query_weights = {item["query_id"]: item["weight_micros"] for item in request["queries"]}
    total_query_weight = sum(query_weights.values())
    source_weights = {
        item["key"]: item["weight_micros"]
        for item in request["soft_preferences"]["source_preferences"]
    }
    source_requested = sum(source_weights.values())
    actor_requested = sum(
        item["weight_micros"] for item in request["soft_preferences"]["actor_preferences"]
    )
    time_requested = request["soft_preferences"]["time_weight_micros"] or 0
    all_locators: list[str] = []
    all_identities: list[str] = []
    neighbor_count = 0
    for candidate in candidates:
        if (
            candidate["source_requested_weight_micros"] != source_requested
            or candidate["actor_requested_weight_micros"] != actor_requested
            or candidate["time_requested_weight_micros"] != time_requested
            or candidate["source_matched_weight_micros"]
            != source_weights.get(candidate["source_key"], 0)
            or candidate["actor_matched_weight_micros"] > actor_requested
            or candidate["time_matched_weight_micros"] not in {0, time_requested}
        ):
            raise ValueError("preference weight evidence does not reconstruct")
        all_locators.append(candidate["locator"])
        all_identities.append(candidate["canonical_identity"])
        for contribution in candidate["contributions"]:
            lane = lanes.get(contribution["provider_id"])
            outcome = outcome_by_provider.get(contribution["provider_id"])
            query_weight = query_weights.get(contribution["query_id"])
            if (
                lane is None
                or query_weight is None
                or not lane["healthy"]
                or not lane["profile_qualified"]
                or outcome is None
                or outcome["status"] != "available"
                or outcome["reason_code"] is not None
            ):
                raise ValueError("contribution provenance is not qualified")
            if (
                contribution["provider_weight_micros"] != lane["weight_micros"]
                or contribution["query_weight_micros"] != query_weight
                or contribution["contribution_score_picos"]
                != _contribution_score(
                    lane["weight_micros"],
                    query_weight,
                    total_query_weight,
                    contribution["provider_rank"],
                )
            ):
                raise ValueError("contribution weight or score evidence differs")
        for neighbor in candidate["neighbors"]:
            neighbor_count += 1
            if (
                bounds["neighbor_radius"] == 0
                or neighbor["relation"] != "neighbor"
                or not 1 <= neighbor["distance"] <= bounds["neighbor_radius"]
                or neighbor["source_key"] != candidate["source_key"]
            ):
                raise ValueError("neighbor evidence violates the requested boundary")
            all_locators.append(neighbor["locator"])
            all_identities.append(neighbor["canonical_identity"])
    if neighbor_count != bounds["returned_neighbors"]:
        raise ValueError("response neighbor count differs from applied bounds")
    duplicate_locator = len(all_locators) != len(set(all_locators))
    duplicate_identity = len(all_identities) != len(set(all_identities))
    if duplicate_locator or duplicate_identity:
        raise ValueError("response locators and canonical identities must be unique")


def _contribution_score(provider_weight: int, query_weight: int, total: int, rank: int) -> int:
    numerator = provider_weight * query_weight * 1_000_000
    denominator = total * (60 + rank)
    quotient, remainder = divmod(numerator, denominator)
    if remainder * 2 > denominator or (remainder * 2 == denominator and quotient % 2):
        quotient += 1
    return quotient


__all__ = (
    "InfinityContextRetrievalV2ContractError",
    "InfinityContextRetrievalV2Error",
    "InfinityContextRetrievalV2Mixin",
)
