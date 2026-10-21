FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/voiceagent
COPY requirements-lock.txt ./
COPY deploy/requirements.txt ./deploy/requirements.txt
RUN pip install --no-cache-dir -r deploy/requirements.txt && pip check \
    && groupadd --gid 10001 voiceagent \
    && useradd --uid 10001 --gid voiceagent --no-create-home voiceagent
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "asyncio", "--http", "h11", "--ws", "websockets", "--ws-max-size", "8192", "--ws-max-queue", "8", "--limit-concurrency", "64", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "10", "--proxy-headers", "--forwarded-allow-ips", "172.30.8.2", "--no-access-log", "--no-server-header"]
