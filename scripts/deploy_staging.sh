#!/bin/sh
set -eu

ENV_FILE="${VIMI_STAGING_ENV_FILE:-.env.staging}"
COMPOSE_FILE="infra/docker/docker-compose.staging.yml"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing staging environment file: $ENV_FILE" >&2
  echo "Copy .env.staging.example and fill real staging values first." >&2
  exit 1
fi

if grep -Eq '^[A-Z0-9_]+=(|CHANGE_ME.*)$' "$ENV_FILE"; then
  echo "Staging environment still contains empty or CHANGE_ME values." >&2
  exit 1
fi

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

compose config --quiet
compose build

# Database authority first. PostgreSQL stays private on the internal network.
compose up -d --wait postgres
compose run --rm --no-deps db-provision
compose run --rm --no-deps migrate

# Ensure the persistent media volume belongs to the non-root runtime UID.
compose run --rm --no-deps media-init

# Temporal may take a short period to become ready; durable workers are configured
# with restart policies and will reconnect rather than requiring external mutation retries.
compose up -d temporal
compose up -d bot worker media-worker destination-worker api caddy

compose ps
