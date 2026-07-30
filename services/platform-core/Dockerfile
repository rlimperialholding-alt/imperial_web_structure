FROM python:3.12-slim AS base
ARG PIP_TRUSTED_HOST
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN addgroup --system --gid 10001 imperial \
    && adduser --system --uid 10001 --ingroup imperial imperial
COPY requirements.txt .
RUN PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" pip install --no-cache-dir -r requirements.txt

FROM base AS test
ARG PIP_TRUSTED_HOST
COPY requirements-dev.txt .
RUN PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" pip install --no-cache-dir -r requirements-dev.txt
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
