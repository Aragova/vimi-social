import os

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from vimi_social.db.base import Base

config = context.config
migration_dsn = os.environ.get("VIMI_MIGRATION_DSN")
if not migration_dsn:
    raise RuntimeError("VIMI_MIGRATION_DSN is required for migrations")
config.set_main_option("sqlalchemy.url", migration_dsn)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=migration_dsn, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text("SET ROLE vimi_migration_owner"))
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
