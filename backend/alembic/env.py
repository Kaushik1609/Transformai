"""
TransformIQ Backend — Alembic Migration Environment

Reads the DATABASE_SYNC_URL from application settings so the database URL
is never hard-coded.  Imports all models so autogenerate can detect schema
changes.
"""
import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ---------------------------------------------------------------------------
# Make sure the backend/app package is importable from this env.py,
# regardless of where alembic is invoked from.
# ---------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
_backend_root = os.path.dirname(_here)
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

# ---------------------------------------------------------------------------
# Alembic config object
# ---------------------------------------------------------------------------
config = context.config

# Configure stdlib logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Override the sqlalchemy.url from application settings
# ---------------------------------------------------------------------------
from app.core.config import settings  # noqa: E402

config.set_main_option("sqlalchemy.url", settings.DATABASE_SYNC_URL)

# ---------------------------------------------------------------------------
# Import Base and all models for autogenerate support
# ---------------------------------------------------------------------------
from app.db.base import Base  # noqa: E402
import app.db.models  # noqa: E402, F401  — registers all models with Base.metadata

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Migration runners
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """
    Run migrations without a live database connection (generates SQL script).
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations against a live database connection.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Run the version-table fix in its OWN committed transaction.
        # Without the explicit `with connection.begin():` the DDL autobegins an
        # outer transaction; alembic's `context.begin_transaction()` then nests
        # as a savepoint and the outer transaction silently rolls back on
        # connection close — migrations would appear to succeed yet never
        # commit. This makes the ensure idempotent AND durable.
        with connection.begin():
            _ensure_wide_version_table(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


def _ensure_wide_version_table(connection) -> None:
    """
    Ensure ``alembic_version.version_num`` can hold every revision id.

    Alembic's default version table column is VARCHAR(32), but this project's
    revision ids are long (e.g. ``0004_phase6_transformation_output_error`` is
    40 characters) and exceeding the width aborts a fresh deployment with
    ``StringDataRightTruncation``. Dev databases were widened manually to
    VARCHAR(100); this makes fresh production databases match by pre-creating
    or widening the table identically. Idempotent and transaction-safe.
    """
    from sqlalchemy import inspect, text

    table_name = "alembic_version"
    if table_name in inspect(connection).get_table_names():
        connection.execute(
            text(
                f"ALTER TABLE {table_name} "
                "ALTER COLUMN version_num TYPE VARCHAR(100)"
            )
        )
    else:
        connection.execute(
            text(
                f"CREATE TABLE {table_name} "
                "(version_num VARCHAR(100) NOT NULL PRIMARY KEY)"
            )
        )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
