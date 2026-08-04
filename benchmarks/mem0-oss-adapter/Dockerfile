FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

WORKDIR /opt/mem0-oss-adapter
COPY . .

RUN chmod 0755 scripts/bootstrap.sh scripts/stage_fastembed_model.py \
    && ./scripts/bootstrap.sh /opt/mem0-oss-venv \
    && PYTHONPATH=/opt/mem0-oss-adapter /opt/mem0-oss-venv/bin/python \
      scripts/stage_fastembed_model.py --destination /opt/models/bge-small-en-v1.5 \
    && mkdir -p /var/lib/mem0-oss /opt/models/bge-small-en-v1.5 \
    && chown -R 65532:65532 /var/lib/mem0-oss /opt/models

ENV PYTHONPATH=/opt/mem0-oss-adapter \
    MEM0_TELEMETRY=false \
    MEM0_TELEMETRY_SAMPLE_RATE=0 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    MEM0_OSS_FASTEMBED_MODEL_DIR=/opt/models/bge-small-en-v1.5 \
    MEM0_OSS_QDRANT_HOST=qdrant \
    MEM0_OSS_QDRANT_PORT=6333 \
    MEM0_OSS_STATE_DIR=/var/lib/mem0-oss \
    MEM0_OSS_EXTRACTION_MODE=raw_passthrough

USER 65532:65532
EXPOSE 8080
CMD ["/opt/mem0-oss-venv/bin/uvicorn", "mem0_oss_adapter.app:app", "--host", "0.0.0.0", "--port", "8080"]
