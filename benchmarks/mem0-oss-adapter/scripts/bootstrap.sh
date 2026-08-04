#!/usr/bin/env bash
set -euo pipefail

adapter_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
venv_path="${1:-${adapter_root}/.venv}"
lock_path="${adapter_root}/runtime-lock.json"
download_dir="$(mktemp -d)"
trap 'rm -rf -- "${download_dir}"' EXIT

if [[ -n "${PYTHON_COMMAND:-}" ]]; then
  python_command="${PYTHON_COMMAND}"
elif command -v python3.11 >/dev/null 2>&1; then
  python_command="$(command -v python3.11)"
elif command -v uv >/dev/null 2>&1; then
  python_command="$(uv python find 3.11)"
else
  python_command="python3"
fi
if ! "${python_command}" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 11))'; then
  echo "CPython 3.11 is required for this immutable lock" >&2
  exit 1
fi

records_path="${download_dir}/lock-records.tsv"
(
  cd "${adapter_root}"
  PYTHONPATH="${adapter_root}" "${python_command}" - "${lock_path}" >"${records_path}" <<'PY'
import sys
from pathlib import Path

from mem0_oss_adapter.runtime_lock import load_runtime_lock
from mem0_oss_adapter.runtime_pin import RUNTIME_PIN

runtime_lock = load_runtime_lock(Path(sys.argv[1]), pin=RUNTIME_PIN)
for artifact in runtime_lock.artifacts:
    print("\t".join((artifact.distribution, artifact.filename, artifact.url)))
PY
)

"${python_command}" -m venv "${venv_path}"
venv_python="${venv_path}/bin/python"
while IFS=$'\t' read -r distribution filename artifact_url; do
  if [[ -z "${distribution}" || -z "${filename}" || -z "${artifact_url}" ]]; then
    echo "runtime lock emitted an invalid artifact record" >&2
    exit 1
  fi
  "${venv_python}" -m pip download \
    --quiet \
    --no-deps \
    --only-binary=:all: \
    --dest "${download_dir}" \
    "${artifact_url}"
done <"${records_path}"

packaging_wheel_path="$(awk -F $'\t' '$1 == "packaging" { print $2 }' "${records_path}")"
if [[ -z "${packaging_wheel_path}" || "${packaging_wheel_path}" == *$'\n'* ]]; then
  echo "runtime lock must contain exactly one packaging wheel" >&2
  exit 1
fi
(
  cd "${adapter_root}"
  PYTHONPATH="${download_dir}/${packaging_wheel_path}:${adapter_root}" \
    "${venv_python}" - "${lock_path}" "${download_dir}" <<'PY'
import sys
from pathlib import Path

from mem0_oss_adapter.runtime_lock import (
    load_runtime_lock,
    verify_downloaded_artifacts,
    verify_wheel_metadata_closure,
)
from mem0_oss_adapter.runtime_pin import RUNTIME_PIN

runtime_lock = load_runtime_lock(Path(sys.argv[1]), pin=RUNTIME_PIN)
wheel_dir = Path(sys.argv[2])
verify_downloaded_artifacts(runtime_lock, wheel_dir)
verify_wheel_metadata_closure(runtime_lock, wheel_dir)
PY
)

mapfile -t runtime_wheels < <(find "${download_dir}" -maxdepth 1 -name '*.whl' -type f -print | sort)
if [[ "${#runtime_wheels[@]}" -eq 0 ]]; then
  echo "runtime lock did not download wheels" >&2
  exit 1
fi
"${venv_python}" -m pip install --quiet --no-deps "${runtime_wheels[@]}"
"${venv_python}" -m pip check
(
  cd "${adapter_root}"
  PYTHONPATH="${adapter_root}" "${venv_python}" - <<'PY'
from importlib.metadata import version

from mem0_oss_adapter.runtime_pin import RUNTIME_PIN

expected = {
    "mem0ai": RUNTIME_PIN.mem0ai_version,
    "fastembed": RUNTIME_PIN.fastembed_version,
    "qdrant-client": RUNTIME_PIN.qdrant_client_version,
}
for distribution, expected_version in expected.items():
    if version(distribution) != expected_version:
        raise SystemExit(f"installed {distribution} does not match the runtime pin")
PY
)
