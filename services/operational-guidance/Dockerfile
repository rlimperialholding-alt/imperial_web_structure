FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/imperial/.local/bin:${PATH}"

RUN groupadd --gid 10001 imperial \
    && useradd --uid 10001 --gid imperial --create-home --shell /usr/sbin/nologin imperial

WORKDIR /app
COPY . /app
RUN pip install --upgrade pip \
    && pip install . \
    && mkdir -p /app/runtime \
    && chown -R imperial:imperial /app/runtime

USER imperial

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/live', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
