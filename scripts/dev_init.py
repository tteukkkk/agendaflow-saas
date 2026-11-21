"""Cria esquema somente em desenvolvimento; em produção usar Alembic."""
from agendaflow.config import PRODUCTION
if PRODUCTION:raise SystemExit('Em produção execute alembic upgrade head, não dev_init.')
from agendaflow.db import Base,engine
from agendaflow import models  # noqa
Base.metadata.create_all(engine)
print('Banco local pronto.')
