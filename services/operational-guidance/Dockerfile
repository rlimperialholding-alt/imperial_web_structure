FROM python:3.12-slim

ARG PIP_TRUSTED_HOST

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/imperial/.local/bin:${PATH}"

RUN groupadd --gid 10001 imperial \
    && useradd --uid 10001 --gid imperial --create-home --shell /usr/sbin/nologin imperial

WORKDIR /app
COPY . /app
RUN --mount=type=secret,id=build_ca,required=false \
    if grep -q "BEGIN CERTIFICATE" /run/secrets/build_ca 2>/dev/null; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/build_ca > /tmp/build-ca.pem; \
      export PIP_CERT=/tmp/build-ca.pem; \
    fi; \
    PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" pip install --upgrade pip "setuptools>=78.1.1" \
    && PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" pip install . \
    && mkdir -p /app/runtime \
    && chown -R imperial:imperial /app/runtime \
    && rm -rf \
      /usr/local/lib/python3.12/site-packages/pip \
      /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
      /usr/local/lib/python3.12/site-packages/setuptools \
      /usr/local/lib/python3.12/site-packages/setuptools-*.dist-info \
      /usr/local/bin/pip \
      /usr/local/bin/pip3 \
      /usr/local/bin/pip3.12; \
    status=$?; rm -f /tmp/build-ca.pem; exit $status

USER imperial

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/live', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
