FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY daemon/ ./daemon/

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin daemon \
    && chown -R daemon:daemon /app
USER daemon

CMD ["python", "-m", "daemon.main"]
