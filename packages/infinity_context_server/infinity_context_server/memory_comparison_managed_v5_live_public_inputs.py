"""Provider-free managed-v5 live public input contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5StatePaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    ManagedMem0V5ExtractionContractBinding,
    require_managed_mem0_v5_extraction_contract_binding,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_v5_extraction_budget import (
    ManagedV5ExtractionTokenBudget,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import Mem0OssAdmissionRequest
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5TransportPort
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
)


class ManagedV5LiveRootError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LivePublicInputs:
    """Exact provider-free inputs admitted before credentials or readiness."""

    cases: tuple[ManagedRunCase, ...]
    current_date: str
    request: Mem0OssAdmissionRequest
    composition_binding: ManagedRunnerCompositionBinding
    mem0_origin: str
    timeout_seconds: float
    state_paths: ManagedMem0V5StatePaths
    credential_paths: ManagedMem0V5CredentialPaths
    extraction_contract_binding: ManagedMem0V5ExtractionContractBinding = field(repr=False)
    extraction_token_budget: ManagedV5ExtractionTokenBudget
    runtime_receipt_boundary: object = field(repr=False)
    trusted_runtime_binding: object = field(repr=False)
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority = field(repr=False)
    mem0_transport: Mem0V5TransportPort | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        try:
            require_managed_mem0_v5_extraction_contract_binding(self.extraction_contract_binding)
        except Exception:
            raise ManagedV5LiveRootError("managed_v5_live_public_inputs_invalid") from None
        if (
            type(self.cases) is not tuple
            or not self.cases
            or any(type(item) is not ManagedRunCase for item in self.cases)
            or type(self.current_date) is not str
            or not self.current_date
            or type(self.request) is not Mem0OssAdmissionRequest
            or type(self.composition_binding) is not ManagedRunnerCompositionBinding
            or type(self.mem0_origin) is not str
            or not self.mem0_origin
            or type(self.state_paths) is not ManagedMem0V5StatePaths
            or type(self.credential_paths) is not ManagedMem0V5CredentialPaths
            or type(self.extraction_contract_binding) is not ManagedMem0V5ExtractionContractBinding
            or type(self.extraction_token_budget) is not ManagedV5ExtractionTokenBudget
            or type(self.receipt_authority) is not Mem0V5ObservedExtractionReceiptAuthority
        ):
            raise ManagedV5LiveRootError("managed_v5_live_public_inputs_invalid")


__all__ = ("ManagedV5LivePublicInputs", "ManagedV5LiveRootError")
