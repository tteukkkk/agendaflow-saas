from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import func, select
from .models import PlanSubscription, Staff, Service, Appointment, utc_now
# Valores são editáveis no checkout Stripe; estes são limites operacionais, não preços oficiais.
PLAN_LIMITS={
 'trial':{'staff':10,'services':30,'bookings':800},
 'starter':{'staff':2,'services':8,'bookings':150},
 'pro':{'staff':10,'services':60,'bookings':1500},
 'business':{'staff':100,'services':1000,'bookings':100000},
}

def subscription(db,org_id):
    return db.scalar(select(PlanSubscription).where(PlanSubscription.organization_id==org_id))

def is_write_allowed(sub):
    if not sub:return False
    if sub.status in ('active','trialing'):
        if sub.status=='trialing':return sub.trial_ends_at>utc_now()
        return True
    return False

def need_active(db,org):
    sub=subscription(db,org.id)
    if not is_write_allowed(sub):
        raise HTTPException(402,'Assinatura inativa ou teste expirado. Atualize seu plano para continuar.')
    return sub

def check_limit(db,org,feature):
    sub=need_active(db,org)
    plan=sub.plan if sub.plan in PLAN_LIMITS else 'trial'
    limit=PLAN_LIMITS[plan][feature]
    if feature=='staff': n=db.scalar(select(func.count(Staff.id)).where(Staff.organization_id==org.id,Staff.active.is_(True)))
    elif feature=='services': n=db.scalar(select(func.count(Service.id)).where(Service.organization_id==org.id,Service.active.is_(True)))
    else:
        first=datetime(utc_now().year,utc_now().month,1)
        n=db.scalar(select(func.count(Appointment.id)).where(Appointment.organization_id==org.id,Appointment.created_at>=first))
    if (n or 0)>=limit:raise HTTPException(403,f'Limite do plano para {feature} atingido. Faça upgrade.')
