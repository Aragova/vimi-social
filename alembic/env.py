from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from vimi_social.db.base import Base

config = context.config
if config.config_file_name is not None and config.file_config.has_section("loggers"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # The login role can deploy migrations but does not own runtime tables.
        # Commit the session-level SET ROLE before Alembic inspects transaction
        # state, otherwise SQLAlchemy 2 autobegin would look like an externally
        # owned transaction and migration DDL could be rolled back on close.
        connection.exec_driver_sql("SET ROLE vimi_migration_owner")
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
