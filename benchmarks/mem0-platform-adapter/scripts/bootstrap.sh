#!/usr/bin/env bash
set -euo pipefail

adapter_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
venv_path="${1:-${adapter_root}/.venv}"
lock_path="${adapter_root}/runtime-lock.json"
download_dir="$(mktemp -d)"
trap 'rm -rf -- "${download_dir}"' EXIT

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required for the frozen dependency graph" >&2
  exit 1
fi
python_command="${PYTHON_COMMAND:-$(uv python find 3.13)}"

records_path="${download_dir}/lock-records.tsv"
if ! (
  cd "${adapter_root}"
  PYTHONPATH="${adapter_root}" "${python_command}" - "${lock_path}" >"${records_path}" <<'PY'
import sys
from pathlib import Path

from mem0_platform_adapter.runtime_lock import load_runtime_lock
from mem0_platform_adapter.runtime_pin import RUNTIME_PIN

runtime_lock = load_runtime_lock(Path(sys.argv[1]), pin=RUNTIME_PIN)
print(
    "\t".join(
        (
            "PIN",
            RUNTIME_PIN.distribution,
            RUNTIME_PIN.version,
            RUNTIME_PIN.source_revision,
            RUNTIME_PIN.wheel_filename,
            RUNTIME_PIN.wheel_sha256,
        )
    )
)
for artifact in runtime_lock.artifacts:
    print(
        "\t".join(
            (
                "ARTIFACT",
                artifact.distribution,
                artifact.version,
                artifact.filename,
                artifact.sha256,
                artifact.url,
            )
        )
    )
PY
); then
  echo "runtime lock validation failed" >&2
  exit 1
fi

distribution=""
version=""
expected_revision=""
expected_wheel=""
expected_sha256=""
artifact_urls=()
runtime_wheels=()
mem0_wheel_path=""
packaging_wheel_path=""
while IFS=$'\t' read -r record_kind field1 field2 field3 field4 field5; do
  if [[ "${record_kind}" == "PIN" ]]; then
    distribution="${field1}"
    version="${field2}"
    expected_revision="${field3}"
    expected_wheel="${field4}"
    expected_sha256="${field5}"
  elif [[ "${record_kind}" == "ARTIFACT" ]]; then
    artifact_urls+=("${field5}")
    if [[ "${field1}" == "${distribution}" ]]; then
      mem0_wheel_path="${download_dir}/${field3}"
    else
      runtime_wheels+=("${download_dir}/${field3}")
    fi
    if [[ "${field1}" == "packaging" ]]; then
      packaging_wheel_path="${download_dir}/${field3}"
    fi
  else
    echo "runtime lock emitted an unknown record" >&2
    exit 1
  fi
done <"${records_path}"
if [[
  -z "${distribution}"
  || "${mem0_wheel_path}" != "${download_dir}/${expected_wheel}"
  || -z "${packaging_wheel_path}"
  || "${#artifact_urls[@]}" -eq 0
]]; then
  echo "runtime lock did not yield the expected artifact graph" >&2
  exit 1
fi

uv venv --seed --python "${python_command}" "${venv_path}"
venv_python="${venv_path}/bin/python"
for artifact_url in "${artifact_urls[@]}"; do
  "${venv_python}" -m pip download \
    --quiet \
    --no-deps \
    --only-binary=:all: \
    --dest "${download_dir}" \
    "${artifact_url}"
done
(
  cd "${adapter_root}"
  PYTHONPATH="${packaging_wheel_path}:${adapter_root}" \
    "${venv_python}" - "${lock_path}" "${download_dir}" <<'PY'
import sys
from pathlib import Path

from mem0_platform_adapter.runtime_lock import (
    load_runtime_lock,
    verify_wheel_metadata_closure,
)
from mem0_platform_adapter.runtime_pin import RUNTIME_PIN

runtime_lock = load_runtime_lock(Path(sys.argv[1]), pin=RUNTIME_PIN)
verify_wheel_metadata_closure(runtime_lock, Path(sys.argv[2]))
PY
)

"${venv_python}" -m pip install --quiet --no-deps "${runtime_wheels[@]}"
"${venv_python}" -m pip install --quiet --force-reinstall --no-deps "${mem0_wheel_path}"
"${venv_python}" -m pip check
(
  cd "${adapter_root}"
  EXPECTED_DISTRIBUTION="${distribution}" \
    EXPECTED_VERSION="${version}" \
    EXPECTED_REVISION="${expected_revision}" \
    EXPECTED_SHA256="${expected_sha256}" \
    "${venv_python}" - <<'PY'
import json
import os
from importlib.metadata import distribution
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from mem0_platform_adapter.manifest import RUNTIME_PIN, _installed_sdk_provenance

installed = distribution(os.environ["EXPECTED_DISTRIBUTION"])
direct_url = json.loads(installed.read_text("direct_url.json") or "{}")
observed = direct_url.get("archive_info", {}).get("hashes", {}).get("sha256")
direct_url_value = direct_url.get("url")
parsed_url = urlparse(direct_url_value) if isinstance(direct_url_value, str) else None
provenance = _installed_sdk_provenance()
if (
    installed.version != os.environ["EXPECTED_VERSION"]
    or observed != os.environ["EXPECTED_SHA256"]
    or RUNTIME_PIN.source_revision != os.environ["EXPECTED_REVISION"]
    or parsed_url is None
    or parsed_url.scheme != "file"
    or parsed_url.params
    or parsed_url.query
    or parsed_url.fragment
    or PurePosixPath(unquote(parsed_url.path)).name != RUNTIME_PIN.wheel_filename
    or provenance["pin_matches"] is not True
):
    raise SystemExit("installed mem0ai distribution lacks verified local-wheel evidence")
print(
    json.dumps(
        {
            "distribution": provenance["distribution"],
            "version": provenance["version"],
            "direct_url_sha256": observed,
            "pin_matches": provenance["pin_matches"],
            "source_revision": provenance["source_revision"],
        },
        sort_keys=True,
    )
)
PY
)
