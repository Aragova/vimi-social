#!/bin/sh
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${VIMI_APP_DB_PASSWORD:?VIMI_APP_DB_PASSWORD is required}"
: "${VIMI_MIGRATOR_DB_PASSWORD:?VIMI_MIGRATOR_DB_PASSWORD is required}"

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=app_password="$VIMI_APP_DB_PASSWORD" \
  --set=migrator_password="$VIMI_MIGRATOR_DB_PASSWORD" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vimi_migration_owner') THEN
        CREATE ROLE vimi_migration_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vimi_migrator') THEN
        CREATE ROLE vimi_migrator LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vimi_app') THEN
        CREATE ROLE vimi_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vimi_source_task_resolver') THEN
        CREATE ROLE vimi_source_task_resolver NOLOGIN;
    END IF;
END
$$;

ALTER ROLE vimi_migration_owner
    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE vimi_migrator
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE vimi_app
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE vimi_source_task_resolver
    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;

ALTER ROLE vimi_migrator PASSWORD :'migrator_password';
ALTER ROLE vimi_app PASSWORD :'app_password';

GRANT vimi_migration_owner TO vimi_migrator;
GRANT vimi_source_task_resolver TO vimi_migration_owner;
REVOKE vimi_migration_owner FROM vimi_app;
REVOKE vimi_source_task_resolver FROM vimi_app;

GRANT CONNECT ON DATABASE vimi TO vimi_migrator, vimi_app;
GRANT CREATE ON DATABASE vimi TO vimi_migration_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO vimi_migration_owner;
GRANT USAGE, CREATE ON SCHEMA public TO vimi_source_task_resolver;
GRANT USAGE ON SCHEMA public TO vimi_app;
SQL
