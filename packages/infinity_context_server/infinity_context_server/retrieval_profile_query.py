"""Execute one admitted profile query, including bounded cancellation cleanup."""

from asyncio import get_running_loop, timeout_at
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from infinity_context_core.features.context_building.public import ProfileQueryAdmissionStatus

from infinity_context_server.retrieval_runtime_lifecycle import complete_despite_cancellation


async def execute_profile_query(
    self, request, *, deadline_monotonic: float, contract_version: str = "context-retrieval.v2"
):
    if contract_version not in ("context-retrieval.v2", "context-retrieval.v3"):
        raise ValueError("Unsupported retrieval boundary")
    if contract_version == "context-retrieval.v2" and request.scope.thread_mode != "exact":
        raise ValueError("V2 requires exact thread selection")
    operation_id = f"profile-query-{uuid4().hex}"
    loop = get_running_loop()
    if loop.time() >= deadline_monotonic:
        raise TimeoutError
    now = datetime.now(UTC)
    query_expires_at = now + timedelta(seconds=deadline_monotonic - loop.time())
    if self.runtime_lifecycle is not None:
        _, start_cancellation = await complete_despite_cancellation(
            self.runtime_lifecycle.start(now=now),
            deadline_monotonic=deadline_monotonic,
        )
        if start_cancellation is not None:
            raise start_cancellation
    admission, admission_cancellation = await complete_despite_cancellation(
        self.registry.begin_profile_query(
            operation_id,
            owner=self.runtime_owner,
            now=now,
            expires_at=query_expires_at,
        ),
        deadline_monotonic=deadline_monotonic,
    )
    if admission.status in {
        ProfileQueryAdmissionStatus.NO_PROFILE,
        ProfileQueryAdmissionStatus.UNAVAILABLE,
    }:
        if admission_cancellation is not None:
            raise admission_cancellation
        raise RuntimeError("retrieval_profile_query_unavailable")
    active = admission.identity
    activation_lease_id = admission.activation_lease_id
    if active is None or activation_lease_id is None:
        raise RuntimeError("retrieval_profile_query_admission_invalid")
    try:
        if admission_cancellation is not None:
            raise admission_cancellation
        async with timeout_at(deadline_monotonic):
            return await self._service_for_active(active, admission_proven=True).execute(
                request,
                **(
                    {"contract_version": contract_version}
                    if contract_version == "context-retrieval.v3"
                    else {}
                ),
            )
    finally:
        try:
            _, close_cancellation = await complete_despite_cancellation(
                self.registry.finish_profile_query(
                    active.profile_id,
                    operation_id,
                    owner=self.runtime_owner,
                    activation_lease_id=activation_lease_id,
                ),
                deadline_monotonic=deadline_monotonic,
            )
        except BaseException:
            self._record_query_fence_close_failure(active.profile_id)
            raise
        if close_cancellation is not None:
            raise close_cancellation
