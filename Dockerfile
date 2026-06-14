# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG MEMO_STACK_EXTRAS="qdrant,openai,graphiti,mcp,docling"
ARG MEMO_STACK_PREINSTALL_TORCH_CPU="true"
ARG MEMO_STACK_TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY packages ./packages

RUN python -m pip install --upgrade pip setuptools wheel \
    && case ",${MEMO_STACK_EXTRAS}," in \
        *,docling,*) \
            if [ "$MEMO_STACK_PREINSTALL_TORCH_CPU" = "true" ]; then \
                python -m pip install --index-url "$MEMO_STACK_TORCH_INDEX_URL" torch torchvision; \
            fi; \
            ;; \
    esac \
    && if [ -n "$MEMO_STACK_EXTRAS" ]; then \
        python -m pip install ".[${MEMO_STACK_EXTRAS}]"; \
    else \
        python -m pip install .; \
    fi

RUN useradd --create-home --home-dir /home/memo --shell /usr/sbin/nologin memo \
    && mkdir -p /var/lib/memo-stack/assets \
    && chown -R memo:memo /var/lib/memo-stack /home/memo

USER memo

EXPOSE 7788

CMD ["python", "-m", "memo_stack_server.main"]
