from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from agendaflow import models
from agendaflow.db import Base
from agendaflow.config import DATABASE_URL
cfg=context.config
target_metadata=Base.metadata

def run_migrations_offline():
    context.configure(url=DATABASE_URL,target_metadata=target_metadata,literal_binds=True,dialect_opts={'paramstyle':'named'})
    with context.begin_transaction():context.run_migrations()

def run_migrations_online():
    from sqlalchemy import create_engine
    with create_engine(DATABASE_URL,pool_pre_ping=True).connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():context.run_migrations()
if context.is_offline_mode():run_migrations_offline()
else:run_migrations_online()
