"""Somente dev: duas empresas fictícias para demonstrar isolamento, nunca executar em produção."""
import random
from datetime import datetime, timedelta
from sqlalchemy import select
from agendaflow.config import PRODUCTION
from agendaflow.db import SessionLocal,Base,engine
from agendaflow.models import (User,Organization,Membership,PlanSubscription,Service,Staff,WorkHours,Customer,Appointment,AuditLog)
from agendaflow.security import password_hash,new_token,hashed_secret
from agendaflow.booking import as_utc_naive,org_day
if PRODUCTION:raise SystemExit('Seed de dados fictícios bloqueado em produção.')
Base.metadata.create_all(engine)
random.seed(42)
with SessionLocal() as db:
    if db.scalar(select(Organization.id)):
        raise SystemExit('Banco não está vazio. Seed abortado para preservar dados.')
    businesses=[('Studio Aurora','studio-aurora','Marina Costa','marina@demo.agendaflow.local','Aurora','Beleza e autocuidado que respeitam seu tempo.'),
                ('Clínica Horizonte','clinica-horizonte','Lucas Almeida','lucas@demo.agendaflow.local','Horizonte','Atendimento humanizado, no seu horário.')]
    first_slug=None
    for name,slug,owner_name,email,_,tagline in businesses:
        owner=User(name=owner_name,email=email,password_hash=password_hash('DemoSeguro#2026'))
        db.add(owner);db.flush()
        org=Organization(name=name,slug=slug,tagline=tagline,email=email,phone='(17) 98888-0000',address='São José do Rio Preto · SP',min_notice_hours=0)
        db.add(org);db.flush()
        db.add_all([Membership(organization_id=org.id,user_id=owner.id,role='owner'),PlanSubscription(organization_id=org.id)])
        offerings=[('Corte personalizado','Cabelo',45,7500),('Coloração e finalização','Beleza',90,18500),('Massagem relaxante','Bem-estar',60,14000),('Tratamento facial','Estética',60,12000)] if slug=='studio-aurora' else [
            ('Avaliação inicial','Atendimento',45,19000),('Sessão de acompanhamento','Atendimento',50,16000),('Orientação e consulta','Atendimento',60,22000)]
        services=[]
        for n,cat,dur,price in offerings:
            s=Service(organization_id=org.id,name=n,category=cat,duration_minutes=dur,price_cents=price,description='Experiência personalizada com nossa equipe.')
            db.add(s);services.append(s)
        staff=[]
        for n,especialidade in [('Ana Rodrigues','Profissional sênior'),('Bruno Martins','Especialista'),('Camila Souza','Atendimento premium')]:
            s=Staff(organization_id=org.id,name=n,specialty=especialidade,active=True)
            db.add(s);staff.append(s)
        db.flush()
        for m in staff:
            for wd in range(7):db.add(WorkHours(staff_id=m.id,weekday=wd,opens_at='09:00',closes_at='18:00',break_start='12:00',break_end='13:00',closed=wd==6))
        customers=[]
        for i,cn in enumerate(['Fernanda Lima','Pedro Oliveira','Beatriz Rocha','Ricardo Pereira','Clara Mendes','Thiago Alves','Juliana Nunes','Roberto Costa','Gabriela Santos','Mariana Lopes','Gustavo Silva','Paula Rodrigues']):
            c=Customer(organization_id=org.id,name=cn,email=f'{slug}-cliente{i}@example.invalid',phone='(17) 90000-0000')
            db.add(c);customers.append(c)
        db.flush()
        now=org_day(org)
        for i in range(36):
            offset=(i%22)-9;day=now+timedelta(days=offset)
            while day.weekday()==6:day+=timedelta(days=1)
            staff_index=i%3; service=services[i%len(services)]
            # múltiplos horários por profissional e dias diferentes
            hour=[9,11,14,16][(i//3)%4]
            start=as_utc_naive(org,day,f'{hour:02d}:00')
            status='completed' if day<now else ('confirmed' if i%7 else 'pending')
            db.add(Appointment(organization_id=org.id,customer_id=customers[i%len(customers)].id,
                service_id=service.id,staff_id=staff[staff_index].id,starts_at=start,
                ends_at=start+timedelta(minutes=service.duration_minutes),status=status,
                price_cents=service.price_cents,manage_token_hash=hashed_secret(new_token())))
        db.add(AuditLog(organization_id=org.id,actor_user_id=owner.id,action='demo.created',details='Dados fictícios para demonstração local.'))
        if not first_slug:first_slug=slug
    db.commit()
    print('Duas empresas fictícias criadas. Login: marina@demo.agendaflow.local / DemoSeguro#2026')
