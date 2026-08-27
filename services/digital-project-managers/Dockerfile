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
    --mount=type=secret,id=build_ca,required=false \
    if grep -q "BEGIN CERTIFICATE" /run/secrets/build_ca 2>/dev/null; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/build_ca > /tmp/build-ca.pem; \
      export PIP_CERT=/tmp/build-ca.pem; \
    fi; \
    PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" python -m pip install .; \
    status=$?; rm -f /tmp/build-ca.pem; exit $status

FROM base AS test
COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=secret,id=build_ca,required=false \
    if grep -q "BEGIN CERTIFICATE" /run/secrets/build_ca 2>/dev/null; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/build_ca > /tmp/build-ca.pem; \
      export PIP_CERT=/tmp/build-ca.pem; \
    fi; \
    PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" python -m pip install ".[dev]"; \
    status=$?; rm -f /tmp/build-ca.pem; exit $status
USER 10001:10001

FROM base AS runtime
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]
