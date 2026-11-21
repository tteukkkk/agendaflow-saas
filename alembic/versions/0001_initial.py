"""Schema inicial isolado por empresa. Revisões futuras devem ser incrementais.
Revision ID: 0001_initial
Revises:
"""
from alembic import op
from agendaflow.db import Base
from agendaflow import models
revision='0001_initial'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    # Instalação inicial sem dados; alterações posteriores exigem migrações explícitas.
    bind=op.get_bind()
    Base.metadata.create_all(bind=bind)

def downgrade():
    # Downgrade destrutivo intencionalmente desabilitado em produção.
    raise RuntimeError('Downgrade destrutivo não suportado; restaure backup ou crie revisão corretiva.')
