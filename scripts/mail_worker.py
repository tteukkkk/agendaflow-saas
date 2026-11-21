"""Worker externo periódico: python -m scripts.mail_worker"""
import smtplib
import ssl
from email.message import EmailMessage
from sqlalchemy import select
from agendaflow.config import SMTP_HOST,SMTP_PORT,SMTP_USERNAME,SMTP_PASSWORD,SMTP_FROM
from agendaflow.db import SessionLocal
from agendaflow.models import EmailOutbox,utc_now

def send_queued(limit=50):
    if not all((SMTP_HOST,SMTP_USERNAME,SMTP_PASSWORD)):
        print('SMTP não configurado: nenhuma mensagem foi enviada.')
        return 0
    count=0
    with SessionLocal() as db:
        items=db.scalars(select(EmailOutbox).where(EmailOutbox.status=='queued',EmailOutbox.attempts<5)
            .order_by(EmailOutbox.id).limit(limit).with_for_update(skip_locked=True)).all()
        # single worker recommended. Full transactional outbox with leases + retry/backoff needed for horizontal scale.
        for entry in items:
            try:
                msg=EmailMessage()
                msg['From']=SMTP_FROM;msg['To']=entry.to_email;msg['Subject']=entry.subject
                msg.set_content(entry.body)
                with smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=15) as server:
                    server.starttls(context=ssl.create_default_context())
                    server.login(SMTP_USERNAME,SMTP_PASSWORD)
                    server.send_message(msg)
                entry.status='sent';entry.sent_at=utc_now();count+=1
            except (OSError,smtplib.SMTPException) as error:
                entry.attempts+=1
                if entry.attempts>=5:entry.status='failed'
                print(f'Falha no envio de mensagem #{entry.id}: {type(error).__name__}')
            db.commit()
    print(f'Mensagens enviadas: {count}')
    return count
if __name__=='__main__':send_queued()
