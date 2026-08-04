# Free Game Tracker (newsroom) — Stage 1.2 portable image (Linux AMD64)
FROM python:3.12-slim-bookworm

LABEL clank.id="free-game-tracker"
LABEL clank.stage="1.2"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEWSROOM_DATABASE_PATH=/app/data/newsroom.db \
    NEWSROOM_REPORTS_DIR=/app/data/reports

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin clank

COPY pyproject.toml README.md ./
COPY newsroom ./newsroom
COPY scripts ./scripts

RUN pip install --upgrade pip \
    && pip install . \
    && mkdir -p /app/data/reports \
    && chown -R clank:clank /app

USER clank

ENTRYPOINT ["/bin/sh", "/app/scripts/entrypoint.sh"]
CMD ["run"]
