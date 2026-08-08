# Free Game Tracker (newsroom) — Linux AMD64 production image.
# Immutable release artifact: built from a reviewed commit, never edited in place.
FROM python:3.12-slim-bookworm

LABEL clank.id="free-game-tracker"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEWSROOM_DATABASE_PATH=/app/data/newsroom.db \
    NEWSROOM_REPORTS_DIR=/app/data/reports \
    NEWSROOM_ALEMBIC_HOME=/app

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin clank

COPY pyproject.toml README.md ./
COPY newsroom ./newsroom
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN pip install --upgrade pip \
    && pip install . \
    && mkdir -p /app/data/reports \
    && chmod +x /app/scripts/*.sh \
    && chown -R clank:clank /app

USER clank

HEALTHCHECK --interval=60s --timeout=20s --start-period=15s --retries=3 \
    CMD ["newsroom", "health"]

ENTRYPOINT ["/bin/sh", "/app/scripts/entrypoint.sh"]
CMD ["run"]
