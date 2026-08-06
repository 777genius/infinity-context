FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY . ./e2e
RUN python -m compileall -q /app/e2e \
    && find /app -type d -name __pycache__ -prune -exec rm -rf '{}' +
USER 65532:65532
CMD ["python", "-m", "e2e.gateway"]
