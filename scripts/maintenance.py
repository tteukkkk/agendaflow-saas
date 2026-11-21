"""Manutenção conservadora: remove apenas tokens efêmeros e contadores antigos.
Não exclui contas, reservas ou dados pessoais; retenção demanda política do controlador.
Execução diária: python -m scripts.maintenance
"""
from datetime import timedelta
from sqlalchemy import delete
from agendaflow.db import SessionLocal
from agendaflow.models import ResetToken, EmailVerification, Invite, RateLimitBucket, utc_now


def run():
    now = utc_now()
    with SessionLocal() as db:
        for model in (ResetToken, EmailVerification, Invite):
            db.execute(delete(model).where(model.expires_at < now - timedelta(days=7)))
        db.execute(delete(RateLimitBucket).where(RateLimitBucket.window_started_at < now - timedelta(days=2)))
        db.commit()
    print('Tokens expirados e limites antigos eliminados; dados de clientes preservados.')


if __name__ == '__main__':
    run()
