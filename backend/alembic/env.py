from logging.config import fileConfig

from alembic import context

# Import the app engine + Base so Alembic can use the same connection and
# has full metadata for autogenerate.
from app.database import engine, Base

# Ensure all ORM models are registered on Base.metadata before autogenerate runs.
import app.models  # noqa: F401
import app.painting.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False preserves uvicorn's log handlers when this
    # runs during app startup (fileConfig's default True wipes them out).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=engine.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
