"""Testes de isolamento, negócio e segurança. Usa banco efêmero independente do banco demo."""
import os
import re
import tempfile
import secrets
import hashlib
import hmac
import json
import time
from datetime import timedelta
from pathlib import Path
TEST_ROOT=tempfile.TemporaryDirectory(prefix='agendaflow-v2-tests-')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(TEST_ROOT.name)/'tests.sqlite3')
os.environ['AGENDAFLOW_ENV']='development'
os.environ['AGENDAFLOW_SECRET_KEY']='tests-only-a-random-long-value-for-signed-sessions-2026'
os.environ.pop('STRIPE_SECRET_KEY',None)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,delete
from agendaflow.main import app
from agendaflow.db import Base,engine,SessionLocal
from agendaflow.models import User,Organization,Membership,PlanSubscription,Service,Staff,Customer,Appointment,EmailOutbox,EmailVerification,ResetToken,RateLimitBucket,utc_now
from agendaflow.security import hashed_secret,_attempts
from agendaflow.booking import org_day
from agendaflow import billing,config
Base.metadata.create_all(engine)

@pytest.fixture(autouse=True)
def clear_local_throttles():
    _attempts.clear()
    with SessionLocal() as db:
        db.execute(delete(RateLimitBucket));db.commit()

def token(client,path='/login'):
    html=client.get(path).text
    m=re.search(r'<meta name="csrf-token" content="([^"]+)"',html)
    assert m,html[:500]
    return {'X-CSRF-Token':m.group(1)}

def new_org(client,slug):
    data={'name':'Admin de Teste','business_name':'Studio '+slug,'slug':slug,'email':f'{slug}@example.test','password':'VerdadeiramenteSeguro#2026','accept_terms':True}
    header=token(client,'/signup')
    r=client.post('/api/auth/signup',json=data,headers=header)
    assert r.status_code==201,r.text
    return data,token(client,f'/app/{slug}')

def workday(org):
    day=org_day(org)+timedelta(days=6)
    while day.weekday()==6:day+=timedelta(days=1)
    return day

def make_staff_service(client,slug,headers):
    s=client.post(f'/api/org/{slug}/services',json={'name':'Consulta premium','description':'Teste','category':'Geral','duration_minutes':60,'price_cents':12345,'active':True},headers=headers)
    assert s.status_code==201,s.text
    m=client.post(f'/api/org/{slug}/staff',json={'name':'Profissional da empresa','email':'','specialty':'Especialista','active':True},headers=headers)
    assert m.status_code==201,m.text
    return s.json()['id'],m.json()['id']

def next_booking(client,slug,sid,mid,day,headers,name='Cliente do Teste',at='09:00',email='client@teste.com'):
    return client.post(f'/api/public/{slug}/book',headers=headers,json={
        'service_id':sid,'staff_id':mid,'date':day.isoformat(),'time':at,'name':name,
        'email':email,'phone':'(17) 90000-0000','notes':'Nota de teste','accept_privacy':True})

def test_public_pages_and_headers():
    with TestClient(app) as c:
        for path in ('/','/login','/signup','/forgot-password','/privacy','/terms','/health','/ready'):
            r=c.get(path)
            assert r.status_code==200,(path,r.text[:350])
            assert 'Content-Security-Policy' in r.headers
            assert r.headers['X-Frame-Options']=='DENY'
        assert '14 dias' in c.get('/').text

def test_csrf_and_signup_terms():
    with TestClient(app) as c:
        h=token(c,'/signup'); payload={'name':'Teste Completo','email':'invalid@x','password':'Senhasegura#2026','business_name':'Negócio','slug':'test-csrf-term','accept_terms':False}
        assert c.post('/api/auth/signup',json=payload).status_code==403
        assert c.post('/api/auth/signup',json=payload,headers=h).status_code==422

def test_signup_trial_workspace_and_tenant_isolation():
    with TestClient(app) as alice,TestClient(app) as bob:
        a,ah=new_org(alice,'empresa-alice')
        b,bh=new_org(bob,'empresa-bob')
        assert alice.get('/app/empresa-alice').status_code==200
        assert bob.get('/app/empresa-bob').status_code==200
        assert alice.get('/app/empresa-bob').status_code==404
        assert bob.get('/app/empresa-alice/billing').status_code==404
        assert alice.get('/api/org/empresa-bob/bookings').status_code==404
        assert alice.get('/api/org/empresa-alice/billing').json()['status']=='trialing'
        with SessionLocal() as db:
            u=db.scalar(select(User).where(User.email==a['email']))
            assert u.terms_accepted_at
            assert u.email_verified_at is None
            assert db.scalar(select(EmailVerification).where(EmailVerification.user_id==u.id))

def test_tenant_objects_and_untrusted_foreign_ids_are_rejected():
    with TestClient(app) as alice,TestClient(app) as bob:
        a,ah=new_org(alice,'corte-tenant-a');b,bh=new_org(bob,'corte-tenant-b')
        sa,ma=make_staff_service(alice,a['slug'],ah)
        sb,mb=make_staff_service(bob,b['slug'],bh)
        dbres=alice.patch(f'/api/org/corte-tenant-a/services/{sb}',json={'name':'Vazamento','description':'','category':'Geral','duration_minutes':60,'price_cents':100,'active':True},headers=ah)
        assert dbres.status_code==404
        day=workday(Organization(timezone='America/Sao_Paulo',booking_window_days=60))
        assert alice.get('/api/public/corte-tenant-a/availability',params={'service_id':sb,'staff_id':ma,'date':day.isoformat()}).status_code==404
        assert alice.get('/api/public/corte-tenant-a/availability',params={'service_id':sa,'staff_id':mb,'date':day.isoformat()}).status_code==404
        assert alice.get(f'/app/corte-tenant-b/customers').status_code==404

def test_booking_collision_cancel_and_reschedule():
    with TestClient(app) as c:
        data,h=new_org(c,'booking-flow')
        sid,mid=make_staff_service(c,data['slug'],h)
        day=workday(Organization(timezone='America/Sao_Paulo',booking_window_days=60))
        slots=c.get('/api/public/booking-flow/availability',params={'service_id':sid,'staff_id':mid,'date':day.isoformat()}).json()['slots']
        assert '09:00' in slots and '12:00' not in slots
        first=next_booking(c,data['slug'],sid,mid,day,h)
        assert first.status_code==201,first.text
        second=next_booking(c,data['slug'],sid,mid,day,h,email='second@test.com')
        assert second.status_code==409
        url=first.json()['manage_url'];token_value=url.removeprefix('/m/')
        assert c.get(url).status_code==200
        move=c.post('/api/manage/reschedule',headers=h,json={'token':token_value,'date':day.isoformat(),'time':'10:00'})
        assert move.status_code==200,move.text
        cancel=c.post('/api/manage/cancel',headers=h,json={'token':token_value})
        assert cancel.status_code==200,cancel.text
        assert c.post('/api/manage/cancel',headers=h,json={'token':token_value}).status_code==409
        assert '10:00' in c.get('/api/public/booking-flow/availability',params={'service_id':sid,'staff_id':mid,'date':day.isoformat()}).json()['slots']
        with SessionLocal() as db:
            org=db.scalar(select(Organization).where(Organization.slug==data['slug']))
            a=db.scalar(select(Appointment).where(Appointment.organization_id==org.id))
            assert a.privacy_consent_at
            assert a.manage_token_hash==hashed_secret(token_value)
            assert token_value not in a.manage_token_hash
            assert db.scalar(select(EmailOutbox).where(EmailOutbox.organization_id==org.id))

def test_public_booking_privacy_consent_and_expired_trial():
    with TestClient(app) as c:
        data,h=new_org(c,'expired-trial')
        sid,mid=make_staff_service(c,data['slug'],h)
        day=workday(Organization(timezone='America/Sao_Paulo',booking_window_days=60))
        payload={'service_id':sid,'staff_id':mid,'date':day.isoformat(),'time':'09:00','name':'Teste','email':'foo@example.com','accept_privacy':False}
        assert c.post('/api/public/expired-trial/book',headers=h,json=payload).status_code==422
        with SessionLocal() as db:
            org=db.scalar(select(Organization).where(Organization.slug=='expired-trial'))
            sub=db.scalar(select(PlanSubscription).where(PlanSubscription.organization_id==org.id))
            sub.trial_ends_at=utc_now()-timedelta(days=1);db.commit()
        payload['accept_privacy']=True
        assert c.post('/api/public/expired-trial/book',headers=h,json=payload).status_code==402
        assert c.post('/api/org/expired-trial/services',headers=h,json={'name':'Outro','description':'','category':'Geral','duration_minutes':60,'price_cents':200,'active':True}).status_code==402
        assert c.get('/api/org/expired-trial/billing').status_code==200

def test_plan_limits():
    with TestClient(app) as c:
        data,h=new_org(c,'plan-limits')
        with SessionLocal() as db:
            org=db.scalar(select(Organization).where(Organization.slug=='plan-limits'))
            sub=db.scalar(select(PlanSubscription).where(PlanSubscription.organization_id==org.id))
            sub.plan='starter';sub.status='active';db.commit()
        for i in range(8):
            r=c.post('/api/org/plan-limits/services',headers=h,json={'name':f'Serviço {i}','description':'','category':'Geral','duration_minutes':45,'price_cents':1000,'active':True})
            assert r.status_code==201,(i,r.text)
        assert c.post('/api/org/plan-limits/services',headers=h,json={'name':'Limitado','description':'','category':'Geral','duration_minutes':45,'price_cents':1000,'active':True}).status_code==403

def test_export_neutralizes_formula_and_tenant_data():
    with TestClient(app) as c:
        data,h=new_org(c,'csv-company');sid,mid=make_staff_service(c,data['slug'],h)
        day=workday(Organization(timezone='America/Sao_Paulo',booking_window_days=60))
        r=next_booking(c,data['slug'],sid,mid,day,h,name='=1+1',email='csv@example.com')
        assert r.status_code==201
        csv_result=c.get('/api/org/csv-company/export/bookings.csv')
        assert csv_result.status_code==200
        assert "'=1+1" in csv_result.text

def test_team_invitations_are_one_time_and_tenant_scoped():
    with TestClient(app) as owner,TestClient(app) as invited:
        data,h=new_org(owner,'invite-company')
        res=owner.post('/api/org/invite-company/invite',headers=h,json={'email':'colaborador@teste.com','role':'manager'})
        assert res.status_code==201,res.text
        with SessionLocal() as db:
            email=db.scalar(select(EmailOutbox).where(EmailOutbox.subject.like('%Convite%')))
            assert email
            tk=re.search(r'/invite/([^\s]+)',email.body).group(1)
        ah=token(invited,f'/invite/{tk}')
        accept=invited.post('/api/auth/invite',headers=ah,json={'token':tk,'name':'Colaborador Teste','password':'SenhaConvidado#2026'})
        assert accept.status_code==200,accept.text
        assert invited.get('/app/invite-company/services').status_code==200
        assert invited.get('/app/invite-company/billing').status_code==404
        ah=token(invited,'/app/invite-company')
        assert invited.post('/api/auth/invite',headers=ah,json={'token':tk,'name':'Colaborador Teste','password':'SenhaConvidado#2026'}).status_code==404

def test_password_reset_revokes_existing_session():
    with TestClient(app) as c:
        data,h=new_org(c,'reset-company')
        request=c.post('/api/auth/forgot',headers=h,json={'email':data['email']})
        assert request.status_code==200
        with SessionLocal() as db:
            out=db.scalars(select(EmailOutbox).order_by(EmailOutbox.id.desc())).first()
            token_value=re.search(r'/reset-password/([^\s]+)',out.body).group(1)
        change=c.post('/api/auth/reset',headers=h,json={'token':token_value,'password':'NovaSenhaMuitoForte#2026'})
        assert change.status_code==200,change.text
        assert c.get('/api/me').status_code==401
        h=token(c,'/login')
        assert c.post('/api/auth/login',headers=h,json={'email':data['email'],'password':'NovaSenhaMuitoForte#2026'}).status_code==200
        h=token(c,'/app/reset-company')
        assert c.post('/api/auth/reset',headers=h,json={'token':token_value,'password':'OutraSenhaMuitoForte#2026'}).status_code==400

def test_checkout_fails_closed_without_credentials():
    with TestClient(app) as c:
        data,h=new_org(c,'stripe-unconfigured')
        r=c.post('/api/org/stripe-unconfigured/billing/checkout',headers=h,json={'plan':'pro'})
        assert r.status_code==503,r.text
        assert c.get('/api/org/stripe-unconfigured/billing').json()['payment_setup'] is False

def test_webhook_verification_replay_and_subscription_event(monkeypatch):
    monkeypatch.setattr(config,'STRIPE_WEBHOOK_SECRET','whsec_testing')
    monkeypatch.setattr(config,'STRIPE_PRICE_PRO','price_testing_pro')
    monkeypatch.setitem(billing.PRICE_BY_PLAN,'pro','price_testing_pro')
    with TestClient(app) as c:
        data,h=new_org(c,'webhook-test')
        with SessionLocal() as db:
            org=db.scalar(select(Organization).where(Organization.slug=='webhook-test'))
            oid=org.id
        obj={'id':'sub_test_webhook','customer':'cus_test_webhook','status':'active',
             'metadata':{'organization_id':str(oid)},'items':{'data':[{'price':{'id':'price_testing_pro'}}]}}
        event={'id':'evt_test_webhook_1','type':'customer.subscription.created','data':{'object':obj}}
        payload=json.dumps(event).encode()
        stamp=str(int(time.time()));signature=hmac.new(b'whsec_testing',stamp.encode()+b'.'+payload,hashlib.sha256).hexdigest()
        headers={'Stripe-Signature':f't={stamp},v1={signature}','Content-Type':'application/json'}
        response=c.post('/webhooks/stripe',headers=headers,content=payload)
        assert response.status_code==200,response.text
        assert c.post('/webhooks/stripe',headers=headers,content=payload).json()['duplicate'] is True
        billing_status=c.get('/api/org/webhook-test/billing').json()
        assert billing_status['plan']=='pro' and billing_status['status']=='active'
        invalid=c.post('/webhooks/stripe',headers={'Stripe-Signature':'t=1,v1=bad'},content=payload)
        assert invalid.status_code==400

def test_dark_mode_accessibility_and_migration_files():
    base=Path(__file__).parents[1]
    css=(base/'static/styles.css').read_text()
    js=(base/'static/app.js').read_text()
    assert ':root[data-theme="dark"]' in css
    assert 'prefers-reduced-motion' in css
    assert 'IntersectionObserver' in js
    assert (base/'alembic/versions/0001_initial.py').is_file()
    assert (base/'Dockerfile').is_file()

def test_composite_foreign_keys_reject_cross_tenant_booking_even_in_database():
    """A restrição continua valendo se alguma rota esquecer filtro de empresa."""
    from sqlalchemy.exc import IntegrityError
    from agendaflow.models import Appointment
    with TestClient(app) as ca,TestClient(app) as cb:
        a,ah=new_org(ca,'db-foreign-tenant-a')
        b,bh=new_org(cb,'db-foreign-tenant-b')
        sa,ma=make_staff_service(ca,a['slug'],ah)
        sb,mb=make_staff_service(cb,b['slug'],bh)
        with SessionLocal() as db:
            orga=db.scalar(select(Organization).where(Organization.slug==a['slug']))
            orgb=db.scalar(select(Organization).where(Organization.slug==b['slug']))
            c=Customer(organization_id=orgb.id,name='Outra empresa',email='outro@company.test')
            db.add(c);db.commit()
            now=utc_now()+timedelta(days=3)
            db.add(Appointment(organization_id=orga.id,customer_id=c.id,staff_id=ma,service_id=sa,
                starts_at=now,ends_at=now+timedelta(hours=1),manage_token_hash=hashed_secret('forbidden-cross-tenant-unique')))
            with pytest.raises(IntegrityError):db.commit()
            db.rollback()

def test_late_stripe_event_does_not_downgrade_subscription(monkeypatch):
    from agendaflow.models import WebhookEvent
    monkeypatch.setattr(config,'STRIPE_PRICE_PRO','price_test_pro')
    monkeypatch.setitem(billing.PRICE_BY_PLAN,'pro','price_test_pro')
    with TestClient(app) as c:
        data,h=new_org(c,'ordered-stripe-events')
        with SessionLocal() as db:
            org=db.scalar(select(Organization).where(Organization.slug==data['slug']))
            sub=db.scalar(select(PlanSubscription).where(PlanSubscription.organization_id==org.id))
            oid=org.id
            base={'id':'sub_ordered','customer':'cus_ordered','metadata':{'organization_id':str(oid)},'items':{'data':[{'price':{'id':'price_test_pro'}}]}}
            billing.process_webhook(db,{'id':'evt_ordered_later','type':'customer.subscription.updated','created':2000,
                                        'data':{'object':{**base,'status':'active'}}})
            billing.process_webhook(db,{'id':'evt_ordered_earlier','type':'customer.subscription.updated','created':1000,
                                        'data':{'object':{**base,'status':'canceled'}}})
            assert db.scalar(select(PlanSubscription).where(PlanSubscription.organization_id==oid)).status=='active'

def test_returning_customer_can_purchase_new_subscription_after_cancellation(monkeypatch):
    monkeypatch.setitem(billing.PRICE_BY_PLAN,'pro','price_test_upgrade')
    with TestClient(app) as c:
        data,h=new_org(c,'renewed-subscription')
        with SessionLocal() as db:
            oid=db.scalar(select(Organization.id).where(Organization.slug==data['slug']))
            first={'id':'sub_old','customer':'cus_returning','status':'canceled',
                   'metadata':{'organization_id':str(oid)},'items':{'data':[{'price':{'id':'price_test_upgrade'}}]}}
            second={**first,'id':'sub_new','status':'active'}
            billing.process_webhook(db,{'id':'evt_subscription_old','type':'customer.subscription.deleted','created':1000,'data':{'object':first}})
            billing.process_webhook(db,{'id':'evt_subscription_new','type':'customer.subscription.created','created':2000,'data':{'object':second}})
            sub=db.scalar(select(PlanSubscription).where(PlanSubscription.organization_id==oid))
            assert sub.status=='active' and sub.stripe_subscription_id=='sub_new'
