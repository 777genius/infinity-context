# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG MEMO_STACK_EXTRAS="qdrant,openai,graphiti,mcp"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY packages ./packages

RUN python -m pip install --upgrade pip setuptools wheel \
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
