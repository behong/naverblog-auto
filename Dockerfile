FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8765 \
    APP_OPEN_BROWSER=false

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser app.py ./app.py
COPY --chown=appuser:appuser admin_auth.py ./admin_auth.py
COPY --chown=appuser:appuser automation_store.py ./automation_store.py
COPY --chown=appuser:appuser toss_open_api.py ./toss_open_api.py
COPY --chown=appuser:appuser toss_collector.py ./toss_collector.py
COPY --chown=appuser:appuser telegram_approval.py ./telegram_approval.py
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser static ./static

USER appuser

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3).read()"]

CMD ["python", "app.py"]
