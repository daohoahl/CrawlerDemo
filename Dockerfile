# =============================================================================
# Crawler Worker (EC2 ASG container image)
#
# Build:
#   docker build -t crawler-worker:latest .
#
# Run locally:
#   docker run --rm -it \
#     -e CRAWLER_SCHEDULE_MODE=once \
#     -e CRAWLER_SQS_QUEUE_URL=... \
#     -e CRAWLER_AWS_REGION=ap-southeast-1 \
#     crawler-worker:latest
# =============================================================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Non-root user
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
ENV PYTHONPATH=/app/src

USER app

# Long-running APScheduler loop (`schedule_mode=interval` by default)
CMD ["python", "-m", "crawlerdemo.worker"]
