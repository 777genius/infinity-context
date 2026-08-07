FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY --from=source-authority manifest.json /run/source-authority/manifest.json
COPY --from=phase-c-authority attestation /run/phase-c-authority/attestation
COPY mem0-oss-adapter-v5/pyproject.toml mem0-oss-adapter-v5/uv.lock mem0-oss-adapter-v5/runtime-lock.json mem0-oss-adapter-v5/README.md ./
COPY mem0-oss-adapter-v5/Dockerfile mem0-oss-adapter-v5/compose.hosted-canary.yaml ./deploy/
COPY mem0-oss-adapter-v5/mem0_oss_adapter_v5 ./mem0_oss_adapter_v5
COPY mem0-oss-adapter/mem0_oss_adapter ./mem0_oss_adapter
COPY mem0-oss-adapter/runtime-pin.json ./runtime-pin.json
COPY mem0-oss-adapter/scripts/stage_fastembed_model.py ./scripts/stage_fastembed_model.py
COPY phase-c-canary/phase_c_canary ./phase_c_canary

RUN --mount=type=secret,id=source_authority_manifest_sha256,required=true python - <<'PY'
import hashlib
import json
import pathlib
import tomllib
import urllib.request

lock = json.loads(pathlib.Path("runtime-lock.json").read_text())
from mem0_oss_adapter_v5.source_authority import verify_source_authority
verify_source_authority(
    manifest_path=pathlib.Path("/run/source-authority/manifest.json"),
    expected_manifest_sha256=pathlib.Path(
        "/run/secrets/source_authority_manifest_sha256"
    ).read_text().strip(),
    installed_root=pathlib.Path("/app"),
    phase_c_authority_root=pathlib.Path("/run/phase-c-authority"),
)
resolved = {
    item["name"].lower().replace("_", "-"): item["version"]
    for item in tomllib.loads(pathlib.Path("uv.lock").read_text())["package"]
}
for artifact in lock["artifacts"]:
    name = artifact["distribution"].lower().replace("_", "-")
    if resolved.get(name) != artifact["version"]:
        raise SystemExit("runtime_lock_uv_closure_mismatch")
wheelhouse = pathlib.Path("/tmp/wheelhouse")
wheelhouse.mkdir()
for artifact in lock["artifacts"]:
    target = wheelhouse / artifact["filename"]
    with urllib.request.urlopen(artifact["url"], timeout=120) as response:
        content = response.read()
    if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
        raise SystemExit("runtime_lock_artifact_invalid")
    target.write_bytes(content)
PY
RUN python -m pip install --no-index --no-deps /tmp/wheelhouse/*.whl \
    && PYTHONPATH=/app python scripts/stage_fastembed_model.py \
         --destination /opt/models/bge-small-en-v1.5 \
    && python -m compileall -q /app/mem0_oss_adapter_v5 \
    && find /app -type d -name __pycache__ -prune -exec rm -rf '{}' + \
    && rm -rf /tmp/wheelhouse

USER 65532:65532
EXPOSE 19091
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    MEM0_TELEMETRY=false \
    MEM0_TELEMETRY_SAMPLE_RATE=0 \
    MEM0_OSS_FASTEMBED_MODEL_DIR=/opt/models/bge-small-en-v1.5
CMD ["uvicorn", "mem0_oss_adapter_v5.composition:build_app_from_environment", "--factory", "--host", "127.0.0.1", "--port", "19091", "--no-access-log", "--no-proxy-headers"]
