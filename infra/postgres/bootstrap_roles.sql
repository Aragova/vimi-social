-- Development/CI role bootstrap. Production must provision equivalent roles
-- through infrastructure automation and real secret management.
--
-- This script intentionally creates login roles with PASSWORD NULL because the
-- local/CI PostgreSQL instances use host trust authentication. Do not copy that
-- authentication choice into production.

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
END
$$;

ALTER ROLE vimi_migration_owner
    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE vimi_migrator
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL;
ALTER ROLE vimi_app
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL;

GRANT vimi_migration_owner TO vimi_migrator;
REVOKE vimi_migration_owner FROM vimi_app;

GRANT CONNECT ON DATABASE vimi TO vimi_migrator, vimi_app;
GRANT CREATE ON DATABASE vimi TO vimi_migration_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO vimi_migration_owner;
GRANT USAGE ON SCHEMA public TO vimi_app;
