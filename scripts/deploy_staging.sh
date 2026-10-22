#!/bin/sh
set -eu

ENV_FILE="${VIMI_STAGING_ENV_FILE:-.env.staging}"
COMPOSE_FILE="infra/docker/docker-compose.staging.yml"
COHOST_COMPOSE_FILE="infra/docker/docker-compose.staging.cohost.yml"
COHOST_MODE="${VIMI_STAGING_COHOST:-false}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing staging environment file: $ENV_FILE" >&2
  echo "Copy .env.staging.example and fill real staging values first." >&2
  exit 1
fi

if grep -Eq '^[A-Z0-9_]+=CHANGE_ME.*$' "$ENV_FILE"; then
  echo "Staging environment still contains CHANGE_ME values." >&2
  exit 1
fi

require_env_value() {
  key="$1"
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | head -n 1)"
  if [ -z "$value" ]; then
    echo "Missing required staging value: $key" >&2
    exit 1
  fi
}

for key in \
  VIMI_PUBLIC_HOST \
  VIMI_POSTGRES_BOOTSTRAP_PASSWORD \
  VIMI_APP_DB_PASSWORD \
  VIMI_MIGRATOR_DB_PASSWORD \
  VIMI_TELEGRAM_BOT_TOKEN \
  VIMI_TELEGRAM_WEBHOOK_SECRET \
  VIMI_X_BEARER_TOKEN \
  VIMI_DEST_X_PRIMARY_TOKEN
do
  require_env_value "$key"
done

case "$COHOST_MODE" in
  true|false) ;;
  *)
    echo "VIMI_STAGING_COHOST must be 'true' or 'false'." >&2
    exit 1
    ;;
esac

compose() {
  if [ "$COHOST_MODE" = "true" ]; then
    docker compose \
      --env-file "$ENV_FILE" \
      -f "$COMPOSE_FILE" \
      -f "$COHOST_COMPOSE_FILE" \
      "$@"
  else
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  fi
}

run_one_shot() {
  service="$1"
  compose up \
    --no-deps \
    --force-recreate \
    --abort-on-container-exit \
    --exit-code-from "$service" \
    "$service"
}

compose config --quiet
# All Python services share the same image tag, so one build is sufficient.
compose build bot

# Database authority first. PostgreSQL stays private on the internal network.
compose up -d --wait postgres
run_one_shot db-provision
run_one_shot migrate

# Ensure the persistent media volume belongs to the non-root runtime UID. Keep the
# named completed service container so depends_on: service_completed_successfully
# joins the exact deployment step instead of launching an implicit second run.
run_one_shot media-init

# Temporal may take a short period to become ready; durable workers are configured
# with restart policies and will reconnect rather than requiring external mutation retries.
compose up -d temporal
if [ "$COHOST_MODE" = "true" ]; then
  # Existing host ingress owns 80/443. The co-host override publishes only the
  # bot on loopback for nginx and deliberately leaves Caddy stopped.
  compose up -d bot worker media-worker destination-worker api
else
  compose up -d bot worker media-worker destination-worker api caddy
fi

compose ps
