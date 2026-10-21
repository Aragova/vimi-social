-- Local/CI bootstrap only. Production role provisioning belongs to infrastructure/IAM.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vimi_migration_owner') THEN
        CREATE ROLE vimi_migration_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vimi_migrator') THEN
        CREATE ROLE vimi_migrator LOGIN PASSWORD 'vimi_migrator_local' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vimi_app') THEN
        CREATE ROLE vimi_app LOGIN PASSWORD 'vimi_app_local' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END $$;

GRANT vimi_migration_owner TO vimi_migrator;
GRANT CONNECT ON DATABASE vimi TO vimi_migrator, vimi_app;
GRANT USAGE, CREATE ON SCHEMA public TO vimi_migration_owner;
GRANT USAGE ON SCHEMA public TO vimi_app;
