FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIMI_MEDIA_ROOT=/var/lib/vimi/media

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY apps ./apps
COPY scripts ./scripts

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && groupadd --gid 10001 vimi \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin vimi \
    && mkdir -p /var/lib/vimi/media \
    && chown -R 10001:10001 /var/lib/vimi

USER 10001:10001

CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
