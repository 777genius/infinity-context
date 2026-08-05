# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG INFINITY_CONTEXT_EXTRAS="qdrant,openai,graphiti,mcp,docling,s3"
ARG INFINITY_CONTEXT_PREINSTALL_TORCH_CPU="true"
ARG INFINITY_CONTEXT_TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg gosu tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY packages ./packages

RUN python -m pip install --upgrade pip setuptools wheel \
    && case ",${INFINITY_CONTEXT_EXTRAS}," in \
        *,docling,*) \
            if [ "$INFINITY_CONTEXT_PREINSTALL_TORCH_CPU" = "true" ]; then \
                python -m pip install --index-url "$INFINITY_CONTEXT_TORCH_INDEX_URL" torch torchvision; \
            fi; \
            ;; \
    esac \
    && if [ -n "$INFINITY_CONTEXT_EXTRAS" ]; then \
        python -m pip install ".[${INFINITY_CONTEXT_EXTRAS}]"; \
    else \
        python -m pip install .; \
    fi

RUN useradd --create-home --home-dir /home/memo --shell /usr/sbin/nologin memo \
    && mkdir -p /var/lib/infinity-context/assets \
    && chown -R memo:memo /var/lib/infinity-context /home/memo

COPY docker/infinity-context-entrypoint.sh /usr/local/bin/infinity-context-entrypoint

RUN chmod 0755 /usr/local/bin/infinity-context-entrypoint

ENTRYPOINT ["infinity-context-entrypoint"]

EXPOSE 7788

CMD ["python", "-m", "infinity_context_server.main"]
