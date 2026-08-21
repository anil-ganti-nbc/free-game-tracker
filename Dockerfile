# Free Game Tracker (newsroom) — Linux AMD64 production image.
# Immutable release artifact: built from a reviewed commit, never edited in place.
FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134

# Full Git SHA of the source this image was built from. Must be passed at
# build time (e.g. `--build-arg GIT_REVISION=$(git rev-parse HEAD)`).
# Deliberately NOT derived from a .git directory at runtime -- no .git is
# copied into this image, and even if it were, the running container's
# filesystem is not proof of what was actually built. Defaults to "unknown"
# so a local build with no revision supplied never fabricates an identity.
ARG GIT_REVISION=unknown
LABEL clank.id="free-game-tracker" \
      org.opencontainers.image.revision="${GIT_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEWSROOM_DATABASE_PATH=/app/data/newsroom.db \
    NEWSROOM_REPORTS_DIR=/app/data/reports \
    NEWSROOM_ALEMBIC_HOME=/app \
    NEWSROOM_SOURCE_REVISION=${GIT_REVISION}

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin clank

COPY pyproject.toml README.md requirements.container.lock ./
COPY newsroom ./newsroom
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN pip install --require-hashes -r requirements.container.lock \
    && pip install --no-deps . \
    && mkdir -p /app/data/reports \
    && chmod +x /app/scripts/*.sh \
    && chown -R clank:clank /app

USER clank

HEALTHCHECK --interval=60s --timeout=20s --start-period=15s --retries=3 \
    CMD ["newsroom", "health"]

ENTRYPOINT ["/bin/sh", "/app/scripts/entrypoint.sh"]
CMD ["run"]
