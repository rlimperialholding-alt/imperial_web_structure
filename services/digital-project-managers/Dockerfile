# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base

ARG PIP_TRUSTED_HOST

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --home /nonexistent app

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations

RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" python -m pip install .

FROM base AS test
COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" python -m pip install ".[dev]"
USER 10001:10001

FROM base AS runtime
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]
