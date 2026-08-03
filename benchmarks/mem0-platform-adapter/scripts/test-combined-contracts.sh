#!/usr/bin/env bash
set -euo pipefail

adapter_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${INFINITY_CONTEXT_ROOT:-}" ]]; then
  echo "INFINITY_CONTEXT_ROOT must name an explicit Infinity Context checkout" >&2
  exit 2
fi
if [[ ! -d "${INFINITY_CONTEXT_ROOT}" ]]; then
  echo "INFINITY_CONTEXT_ROOT is not a directory: ${INFINITY_CONTEXT_ROOT}" >&2
  exit 2
fi
infinity_root="$(cd -- "${INFINITY_CONTEXT_ROOT}" && pwd)"

required_modules=(
  "packages/infinity_context_server/infinity_context_server/memory_comparison_mem0_contract.py"
  "packages/infinity_context_server/infinity_context_server/memory_comparison_mem0_platform_contract.py"
  "packages/infinity_context_server/infinity_context_server/memory_comparison_mem0_runtime_attestation.py"
  "packages/infinity_context_server/infinity_context_server/memory_comparison_service_probes.py"
)
for module in "${required_modules[@]}"; do
  if [[ ! -f "${infinity_root}/${module}" ]]; then
    echo "required combined-contract module is absent: ${infinity_root}/${module}" >&2
    exit 2
  fi
done
adapter_python="${adapter_root}/.venv/bin/python"
if [[ ! -x "${adapter_python}" ]]; then
  echo "adapter .venv is absent; run scripts/bootstrap.sh first" >&2
  exit 2
fi

combined_pythonpath="${adapter_root}:${infinity_root}"
for package_root in "${infinity_root}"/packages/*; do
  if [[ -d "${package_root}" ]]; then
    combined_pythonpath="${combined_pythonpath}:${package_root}"
  fi
done
if [[ -n "${PYTHONPATH:-}" ]]; then
  combined_pythonpath="${combined_pythonpath}:${PYTHONPATH}"
fi

export MEM0_ADAPTER_REQUIRE_ROOT_CONTRACTS=1
export PYTHONPATH="${combined_pythonpath}"
cd "${adapter_root}"
exec "${adapter_python}" -m pytest -m contract --maxfail=1 -rs
