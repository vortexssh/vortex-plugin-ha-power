FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VORTEX_DATA_DIR=/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY daemon/ ./daemon/
COPY scripts/entrypoint.sh /entrypoint.sh

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown -R app:app /app /data \
    && chmod +x /entrypoint.sh

# Start as root so entrypoint can chown the bind-mounted /data, then drop to app.
USER root
ENTRYPOINT ["/entrypoint.sh"]
