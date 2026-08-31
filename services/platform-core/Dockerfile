FROM python:3.12-slim AS base
ARG PIP_TRUSTED_HOST
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN addgroup --system --gid 10001 imperial \
    && adduser --system --uid 10001 --ingroup imperial imperial
COPY requirements.txt .
RUN --mount=type=secret,id=build_ca,required=false \
    if grep -q "BEGIN CERTIFICATE" /run/secrets/build_ca 2>/dev/null; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/build_ca > /tmp/build-ca.pem; \
      export PIP_CERT=/tmp/build-ca.pem; \
    fi; \
    PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" pip install --no-cache-dir -r requirements.txt; \
    status=$?; rm -f /tmp/build-ca.pem; exit $status

FROM base AS test
ARG PIP_TRUSTED_HOST
COPY requirements-dev.txt .
RUN --mount=type=secret,id=build_ca,required=false \
    if grep -q "BEGIN CERTIFICATE" /run/secrets/build_ca 2>/dev/null; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/build_ca > /tmp/build-ca.pem; \
      export PIP_CERT=/tmp/build-ca.pem; \
    fi; \
    PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" pip install --no-cache-dir --no-binary mypy -r requirements-dev.txt; \
    status=$?; rm -f /tmp/build-ca.pem; exit $status
COPY . .
RUN mkdir -p /app/data /app/runtime && chown -R imperial:imperial /app
USER imperial
CMD ["pytest", "-q"]

FROM base AS runtime
COPY . .
RUN mkdir -p /app/data /app/runtime && chown -R imperial:imperial /app
USER imperial
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
