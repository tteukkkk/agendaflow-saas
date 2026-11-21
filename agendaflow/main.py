"""AgendaFlow SaaS v2: multiempresa. Falha fechada: nenhuma rota antiga de admin global."""
import csv
import io
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import config
from .db import Base, engine, get_db
from .models import (User,Organization,Membership,PlanSubscription,Service,Staff,WorkHours,TimeOff,
                     Customer,Appointment,AuditLog,EmailOutbox,ResetToken,EmailVerification,Invite,utc_now)
from .security import (new_token,hashed_secret,password_hash,check_password,valid_email,
                      require_csrf,csrf_token,user_for,require_user,tenant_guard,client_ip,throttle_shared,member_for)
from .booking import (available_slots,lock_staff,start_write,as_utc_naive,org_day,local_dt,zone)
from .plans import subscription,need_active,check_limit,PLAN_LIMITS,is_write_allowed
from .billing import checkout_session,portal_session,verify_signature,process_webhook

ROOT=Path(__file__).resolve().parents[1]
app=FastAPI(title='AgendaFlow SaaS',version='2.0.0',docs_url='/api/docs' if not config.PRODUCTION else None)
app.add_middleware(SessionMiddleware,secret_key=config.SECRET,session_cookie='agendaflow_session',same_site='lax',https_only=config.PRODUCTION,max_age=60*60*24*3)
if config.PRODUCTION:app.add_middleware(TrustedHostMiddleware,allowed_hosts=config.ALLOWED_HOSTS)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
templates=Jinja2Templates(directory=ROOT/'templates')

def money(n:int):return f'R$ {n/100:,.2f}'.replace(',','~').replace('.',',').replace('~','.')
templates.env.filters['money']=money

def fail(message,code=400):raise HTTPException(code,message)

def text_clean(value,max_len=160):return ' '.join(value.split())[:max_len]

def get_org(db,slug):
    org=db.scalar(select(Organization).where(Organization.slug==slug))
    if not org:fail('Estabelecimento não encontrado.',404)
    return org

def json_response(message,**fields):return {'ok':True,'message':message,**fields}

def audit(db,org,user,action,details=''):
    db.add(AuditLog(organization_id=org.id,actor_user_id=user.id if user else None,action=action,details=details[:260]))

def queue_email(db,org,email,subject,body):
    db.add(EmailOutbox(organization_id=org.id,to_email=email,subject=subject,body=body))

def safe_csv(value):
    s=str(value or '')
    return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else s

def template(request,db,name,org=None,**context):
    user=user_for(request,db)
    ctx={'user':user,'csrf':csrf_token(request),'org':org,'request':request,'today':org_day(org) if org else date.today(),
         'subscription':subscription(db,org.id) if org else None,'money':money,
         'active_nav':context.pop('active_nav',''),'support_email':config.SUPPORT_EMAIL,'current_utc':utc_now(),**context}
    if org:
        ctx['membership']=member_for(db,user,org)
    return templates.TemplateResponse(request,name,ctx)

@app.middleware('http')
async def secure_headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    # HTML templates não usam scripts inline.
    response.headers['Content-Security-Policy']=("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
    if config.PRODUCTION:response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    return response

@app.get('/health')
def health():return {'status':'ok','version':'2.0.0'}

@app.get('/ready')
def ready(db:Session=Depends(get_db)):
    db.execute(select(func.count(Organization.id)))
    return {'status':'ready'}

@app.get('/',response_class=HTMLResponse)
def home(request:Request,db:Session=Depends(get_db)):
    return template(request,db,'landing.html')

@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request,db:Session=Depends(get_db)):
    return template(request,db,'auth.html',mode='login')

@app.get('/signup',response_class=HTMLResponse)
def signup_page(request:Request,db:Session=Depends(get_db)):
    return template(request,db,'auth.html',mode='signup')

@app.get('/verify-email/{token}',response_class=HTMLResponse)
def verify_page(request:Request,token:str,db:Session=Depends(get_db)):
    return template(request,db,'auth.html',mode='verify',verification_token=token)

class VerifyInput(BaseModel):token:str

@app.post('/api/auth/verify-email')
def verify_email(data:VerifyInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db)
    token=db.scalar(select(EmailVerification).where(EmailVerification.token_hash==hashed_secret(data.token),EmailVerification.consumed_at.is_(None),EmailVerification.expires_at>utc_now()))
    if not token:fail('Link inválido ou expirado.',400)
    user=db.get(User,token.user_id)
    user.email_verified_at=utc_now();token.consumed_at=utc_now();db.commit()
    return json_response('E-mail confirmado.',redirect='/login')

@app.get('/forgot-password',response_class=HTMLResponse)
def forgot_page(request:Request,db:Session=Depends(get_db)):
    return template(request,db,'auth.html',mode='forgot')

@app.get('/reset-password/{token}',response_class=HTMLResponse)
def reset_page(request:Request,token:str,db:Session=Depends(get_db)):
    return template(request,db,'auth.html',mode='reset',reset_token=token)

@app.get('/invite/{token}',response_class=HTMLResponse)
def invitation_page(request:Request,token:str,db:Session=Depends(get_db)):
    invitation=db.scalar(select(Invite).where(Invite.token_hash==hashed_secret(token),Invite.used_at.is_(None),Invite.expires_at>utc_now()))
    if not invitation:fail('Convite inválido ou expirado.',404)
    org=db.get(Organization,invitation.organization_id)
    return template(request,db,'auth.html',mode='invite',invitation=invitation,invited_org=org,invite_token=token)

class SignupInput(BaseModel):
    name:str=Field(min_length=3,max_length=120)
    email:str=Field(min_length=5,max_length=200)
    password:str=Field(min_length=12,max_length=128)
    business_name:str=Field(min_length=3,max_length=120)
    slug:str=Field(min_length=3,max_length=75)
    accept_terms:bool
class LoginInput(BaseModel):
    email:str=Field(min_length=4,max_length=200)
    password:str
class ForgotInput(BaseModel):email:str
class ResetInput(BaseModel):token:str;password:str=Field(min_length=12,max_length=128)
class InviteInput(BaseModel):
    token:str
    name:str=Field(min_length=3,max_length=120)
    password:str=Field(min_length=12,max_length=128)

@app.post('/api/auth/signup',status_code=201)
def signup(data:SignupInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);throttle_shared('signup:'+client_ip(request),5,3600);start_write(db)
    if not data.accept_terms:fail('É necessário aceitar os termos.',422)
    email=data.email.strip().lower();slug=data.slug.strip().lower()
    if not valid_email(email) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,74}',slug):fail('E-mail ou endereço da empresa inválido.',422)
    if db.scalar(select(User).where(User.email==email)):fail('Este e-mail já está cadastrado. Faça login.',409)
    if db.scalar(select(Organization).where(Organization.slug==slug)):fail('Este endereço já está em uso.',409)
    try:
        user=User(name=text_clean(data.name),email=email,password_hash=password_hash(data.password),terms_accepted_at=utc_now())
        org=Organization(name=text_clean(data.business_name),slug=slug,email=email)
        db.add_all([user,org]);db.flush()
        db.add_all([Membership(organization_id=org.id,user_id=user.id,role='owner'),PlanSubscription(organization_id=org.id)])
        audit(db,org,user,'organization.created')
        verify=new_token()
        db.add(EmailVerification(user_id=user.id,token_hash=hashed_secret(verify),expires_at=utc_now()+timedelta(hours=24)))
        queue_email(db,org,user.email,'Verifique seu e-mail - AgendaFlow',f'Clique para confirmar seu endereço: {config.PUBLIC_BASE_URL}/verify-email/{verify}')
        db.commit()
    except IntegrityError:
        db.rollback();fail('O e-mail ou o endereço já está em uso.',409)
    request.session.clear();request.session['uid']=user.id;request.session['sv']=user.session_version
    return json_response('Empresa criada com teste de 14 dias.',redirect=f'/app/{slug}')

@app.post('/api/auth/login')
def login(data:LoginInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request)
    email=data.email.strip().lower()
    throttle_shared('login:'+client_ip(request),20,300)
    throttle_shared('login-email:'+email,10,300)
    user=db.scalar(select(User).where(User.email==email))
    if not user or not user.active or not check_password(data.password,user.password_hash):fail('E-mail ou senha incorretos.',401)
    request.session.clear();request.session['uid']=user.id;request.session['sv']=user.session_version
    member=db.scalar(select(Membership).where(Membership.user_id==user.id,Membership.active.is_(True)))
    org=db.get(Organization,member.organization_id) if member else None
    return json_response('Bem-vindo!',redirect=f'/app/{org.slug}' if org else '/')

@app.post('/api/auth/logout')
def logout(request:Request):
    require_csrf(request);request.session.clear()
    return json_response('Sessão encerrada.',redirect='/')

@app.post('/api/auth/forgot')
def forgot(data:ForgotInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);throttle_shared('forgot:'+client_ip(request),5,3600)
    user=db.scalar(select(User).where(User.email==data.email.strip().lower()))
    if user:
        token=new_token()
        db.add(ResetToken(user_id=user.id,token_hash=hashed_secret(token),expires_at=utc_now()+timedelta(minutes=30)))
        member=db.scalar(select(Membership).where(Membership.user_id==user.id))
        if member:
            org=db.get(Organization,member.organization_id)
            queue_email(db,org,user.email,'Recuperação de senha - AgendaFlow',
                f'Use o link por até 30 minutos: {config.PUBLIC_BASE_URL}/reset-password/{token}\nSe não solicitou, ignore.')
        db.commit()
    return json_response('Se houver uma conta, você receberá instruções por e-mail.')

@app.post('/api/auth/reset')
def reset(data:ResetInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);throttle_shared('reset:'+client_ip(request),10,3600)
    rec=db.scalar(select(ResetToken).where(ResetToken.token_hash==hashed_secret(data.token),ResetToken.consumed_at.is_(None),ResetToken.expires_at>utc_now()))
    if not rec:fail('Link inválido ou expirado.',400)
    user=db.get(User,rec.user_id)
    user.password_hash=password_hash(data.password)
    user.session_version+=1  # invalida sessões anteriores
    rec.consumed_at=utc_now()
    db.commit();request.session.clear()
    return json_response('Senha alterada. Entre novamente.',redirect='/login')

@app.post('/api/auth/invite')
def accept_invite(data:InviteInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);throttle_shared('invite:'+client_ip(request),10,3600)
    inv=db.scalar(select(Invite).where(Invite.token_hash==hashed_secret(data.token),Invite.used_at.is_(None),Invite.expires_at>utc_now()))
    if not inv:fail('Convite inválido.',404)
    user=db.scalar(select(User).where(User.email==inv.email))
    if user:
        if not check_password(data.password,user.password_hash):fail('Para aceitar, informe sua senha atual.',401)
    else:
        user=User(name=text_clean(data.name),email=inv.email,password_hash=password_hash(data.password))
        db.add(user);db.flush()
    if db.scalar(select(Membership).where(Membership.user_id==user.id,Membership.organization_id==inv.organization_id)):
        fail('Você já faz parte da equipe.',409)
    db.add(Membership(organization_id=inv.organization_id,user_id=user.id,role=inv.role))
    inv.used_at=utc_now();org=db.get(Organization,inv.organization_id)
    audit(db,org,user,'member.joined',inv.role);db.commit()
    request.session.clear();request.session['uid']=user.id;request.session['sv']=user.session_version
    return json_response('Convite aceito.',redirect=f'/app/{org.slug}')

# ---------------- PÁGINAS TENANT (todas com autenticação de membro) ----------------
@app.get('/app/{slug}',response_class=HTMLResponse)
@app.get('/app/{slug}/{page}',response_class=HTMLResponse)
def workspace(request:Request,slug:str,page:str='dashboard',db:Session=Depends(get_db)):
    if page not in ('dashboard','calendar','appointments','customers','services','team','reports','billing','settings'):
        fail('Página não encontrada.',404)
    allowed = ('owner',) if page in ('billing','settings') else ('owner','manager') if page in ('customers','services','team','reports') else ('owner','manager','staff')
    org,user,member=tenant_guard(request,db,slug,allowed)
    bookings=db.scalars(select(Appointment).where(Appointment.organization_id==org.id).order_by(Appointment.starts_at.desc()).limit(200)).all()
    services=db.scalars(select(Service).where(Service.organization_id==org.id).order_by(Service.name)).all()
    staff=db.scalars(select(Staff).where(Staff.organization_id==org.id).order_by(Staff.name)).all()
    customers=db.scalars(select(Customer).where(Customer.organization_id==org.id).order_by(Customer.name)).all()
    members=db.scalars(select(Membership).where(Membership.organization_id==org.id,Membership.active.is_(True))).all()
    by_id={c.id:c for c in customers}
    now=utc_now();month_start=datetime(now.year,now.month,1)
    month_bookings=[b for b in bookings if b.starts_at>=month_start]
    revenue=sum(b.price_cents for b in month_bookings if b.status=='completed')
    upcoming=sorted((b for b in bookings if b.starts_at>=now and b.status in ('confirmed','pending')),key=lambda x:x.starts_at)[:8]
    if member.role=='staff':
        assigned=db.scalar(select(Staff).where(Staff.organization_id==org.id,Staff.user_id==user.id))
        # Conta staff não vinculada a profissional não recebe acesso a dados de clientes
        bookings=[b for b in bookings if assigned and b.staff_id==assigned.id]
        upcoming=[b for b in upcoming if assigned and b.staff_id==assigned.id]
        customers=[]
    if member.role=='staff':
        month_bookings=[b for b in bookings if b.starts_at>=month_start]
        revenue=sum(b.price_cents for b in month_bookings if b.status=='completed')
    for b in bookings:
        b.display_start=local_dt(org,b.starts_at)
        b.display_end=local_dt(org,b.ends_at)
    for b in upcoming:
        b.display_start=local_dt(org,b.starts_at)
    return template(request,db,'workspace.html',org=org,page=page,active_nav=page,
        bookings=bookings,services=services,staff=staff,customers=customers,members=members,
        upcoming=upcoming,stats={'bookings':len(month_bookings),'revenue':revenue,'customers':len(customers),'services':len(services)},
        plan_limits=PLAN_LIMITS.get((subscription(db,org.id) or PlanSubscription()).plan,PLAN_LIMITS['trial']))

@app.get('/r/{slug}',response_class=HTMLResponse)
def public_booking_page(request:Request,slug:str,db:Session=Depends(get_db)):
    org=get_org(db,slug)
    services=db.scalars(select(Service).where(Service.organization_id==org.id,Service.active.is_(True)).order_by(Service.name)).all()
    staff=db.scalars(select(Staff).where(Staff.organization_id==org.id,Staff.active.is_(True)).order_by(Staff.name)).all()
    return template(request,db,'booking.html',org=org,services=services,staff=staff)

@app.get('/m/{token}',response_class=HTMLResponse)
def customer_manage_page(request:Request,token:str,db:Session=Depends(get_db)):
    appointment=db.scalar(select(Appointment).where(Appointment.manage_token_hash==hashed_secret(token)))
    if not appointment:fail('Agendamento não encontrado.',404)
    org=db.get(Organization,appointment.organization_id)
    appointment.display_start=local_dt(org,appointment.starts_at)
    return template(request,db,'manage.html',org=org,booking=appointment,token=token)

@app.get('/api/me')
def me(request:Request,db:Session=Depends(get_db)):
    user=require_user(request,db)
    memberships=db.scalars(select(Membership).where(Membership.user_id==user.id,Membership.active.is_(True))).all()
    return {'name':user.name,'email':user.email,'workspaces':[
        {'slug':db.get(Organization,m.organization_id).slug,'role':m.role} for m in memberships]}

class ServiceInput(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    description:str=Field(default='',max_length=600)
    category:str=Field(default='Geral',max_length=60)
    duration_minutes:int=Field(ge=15,le=480)
    price_cents:int=Field(ge=0,le=10_000_000)
    active:bool=True
class StaffInput(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    email:str=Field(default='',max_length=200)
    specialty:str=Field(default='Profissional',max_length=130)
    active:bool=True
class HoursInput(BaseModel):
    weekday:int=Field(ge=0,le=6)
    opens_at:str
    closes_at:str
    break_start:str=''
    break_end:str=''
    closed:bool=False
class TimeOffInput(BaseModel):
    staff_id:int
    start:str
    end:str
    reason:str=Field(default='Bloqueio de horário',max_length=180)
class SettingsInput(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    tagline:str=Field(default='',max_length=180)
    email:str=Field(default='',max_length=200)
    phone:str=Field(default='',max_length=40)
    address:str=Field(default='',max_length=220)
    timezone:str='America/Sao_Paulo'
    booking_window_days:int=Field(ge=1,le=365)
    slot_step:Literal[15,30,60]
    min_notice_hours:int=Field(ge=0,le=168)
    cancel_notice_hours:int=Field(ge=0,le=168)
    require_approval:bool=False
    privacy_notice:str=Field(default='',max_length=4000)
class StatusInput(BaseModel):status:Literal['pending','confirmed','completed','cancelled','no_show']
class NewBookingInput(BaseModel):
    service_id:int
    staff_id:int
    date:date
    time:str=Field(pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    name:str=Field(min_length=2,max_length=120)
    email:str=Field(min_length=5,max_length=200)
    phone:str=Field(default='',max_length=40)
    notes:str=Field(default='',max_length=1000)
    accept_privacy:bool
class RescheduleInput(BaseModel):
    date:date
    time:str=Field(pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
class InviteRequest(BaseModel):
    email:str
    role:Literal['manager','staff']='staff'

@app.get('/api/org/{slug}/summary')
def tenant_summary(request:Request,slug:str,db:Session=Depends(get_db)):
    org,user,member=tenant_guard(request,db,slug)
    appts=db.scalars(select(Appointment).where(Appointment.organization_id==org.id).order_by(Appointment.starts_at.desc()).limit(300)).all()
    if member.role=='staff':
        staff=db.scalar(select(Staff).where(Staff.organization_id==org.id,Staff.user_id==user.id))
        appts=[b for b in appts if staff and b.staff_id==staff.id]
    return {'organization':org.name,'role':member.role,'bookings':[{
        'id':a.id,'customer':a.customer.name,'service':a.service.name,'staff':a.staff.name,
        'starts_at':local_dt(org,a.starts_at).isoformat(),'status':a.status,'price_cents':a.price_cents} for a in appts]}

@app.post('/api/org/{slug}/services',status_code=201)
def create_service(slug:str,data:ServiceInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db);org,user,_=tenant_guard(request,db,slug,('owner','manager'))
    check_limit(db,org,'services')
    item=Service(organization_id=org.id,name=text_clean(data.name),description=data.description,category=text_clean(data.category),duration_minutes=data.duration_minutes,price_cents=data.price_cents,active=data.active)
    db.add(item);audit(db,org,user,'service.created',item.name);db.commit()
    return {'id':item.id}

@app.patch('/api/org/{slug}/services/{item_id}')
def update_service(slug:str,item_id:int,data:ServiceInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db);org,user,_=tenant_guard(request,db,slug,('owner','manager'));need_active(db,org)
    obj=db.scalar(select(Service).where(Service.organization_id==org.id,Service.id==item_id))
    if not obj:fail('Serviço inexistente.',404)
    for k,v in data.model_dump().items():setattr(obj,k,text_clean(v) if k in ('name','category') else v)
    audit(db,org,user,'service.updated',str(item_id));db.commit()
    return json_response('Serviço atualizado.')

@app.post('/api/org/{slug}/staff',status_code=201)
def add_staff(slug:str,data:StaffInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db);org,user,_=tenant_guard(request,db,slug,('owner','manager'))
    check_limit(db,org,'staff')
    if data.email and not valid_email(data.email):fail('E-mail inválido.',422)
    staff=Staff(organization_id=org.id,name=text_clean(data.name),email=data.email.strip().lower(),specialty=text_clean(data.specialty),active=data.active)
    db.add(staff);db.flush()
    for weekday in range(7):
        db.add(WorkHours(staff_id=staff.id,weekday=weekday,opens_at='09:00',closes_at='18:00',break_start='12:00',break_end='13:00',closed=weekday==6))
    audit(db,org,user,'staff.created',staff.name);db.commit()
    return {'id':staff.id}

@app.patch('/api/org/{slug}/staff/{staff_id}')
def update_staff(slug:str,staff_id:int,data:StaffInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db);org,user,_=tenant_guard(request,db,slug,('owner','manager'));need_active(db,org)
    staff=db.scalar(select(Staff).where(Staff.organization_id==org.id,Staff.id==staff_id))
    if not staff:fail('Profissional inexistente.',404)
    for k,v in data.model_dump().items():setattr(staff,k,v)
    audit(db,org,user,'staff.updated',staff.name);db.commit()
    return json_response('Profissional atualizado.')

@app.put('/api/org/{slug}/staff/{staff_id}/hours')
def update_hours(slug:str,staff_id:int,data:HoursInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db);org,user,_=tenant_guard(request,db,slug,('owner','manager'));need_active(db,org)
    staff=db.scalar(select(Staff).where(Staff.organization_id==org.id,Staff.id==staff_id))
    if not staff:fail('Profissional inexistente.',404)
    from datetime import time
    try:
        opening=time.fromisoformat(data.opens_at);closing=time.fromisoformat(data.closes_at)
        if not data.closed and closing<=opening:fail('Encerramento precisa ser posterior à abertura.',422)
        if data.break_start or data.break_end:
            b_start=time.fromisoformat(data.break_start)
            b_end=time.fromisoformat(data.break_end)
            if not (opening<=b_start<b_end<=closing):fail('Intervalo fora do expediente.',422)
    except ValueError:fail('Horário inválido.',422)
    lock_staff(db,org.id,staff.id)
    hours=db.scalar(select(WorkHours).where(WorkHours.staff_id==staff.id,WorkHours.weekday==data.weekday))
    if not hours:
        hours=WorkHours(staff_id=staff.id,weekday=data.weekday);db.add(hours)
    for k,v in data.model_dump().items():setattr(hours,k,v)
    audit(db,org,user,'hours.updated',str(staff.id));db.commit()
    return json_response('Expediente atualizado.')

@app.post('/api/org/{slug}/time-off',status_code=201)
def add_timeoff(slug:str,data:TimeOffInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db);org,user,_=tenant_guard(request,db,slug,('owner','manager'));need_active(db,org)
    staff=db.scalar(select(Staff).where(Staff.organization_id==org.id,Staff.id==data.staff_id))
    if not staff:fail('Profissional inexistente.',404)
    try:
        start=datetime.fromisoformat(data.start)
        end=datetime.fromisoformat(data.end)
        if start.tzinfo or end.tzinfo:fail('Informe horários locais sem fuso.',422)
        a=as_utc_naive(org,start.date(),start.strftime('%H:%M'))
        b=as_utc_naive(org,end.date(),end.strftime('%H:%M'))
        if b<=a:fail('Período inválido.',422)
    except ValueError:fail('Período inválido.',422)
    lock_staff(db,org.id,staff.id)
    db.add(TimeOff(organization_id=org.id,staff_id=staff.id,starts_at=a,ends_at=b,reason=data.reason))
    audit(db,org,user,'timeoff.created');db.commit()
    return json_response('Horário bloqueado.')

@app.patch('/api/org/{slug}/settings')
def update_settings(slug:str,data:SettingsInput,request:Request,db:Session=Depends(get_db)):
    from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
    require_csrf(request);start_write(db);org,user,_=tenant_guard(request,db,slug,('owner',));need_active(db,org)
    try:ZoneInfo(data.timezone)
    except ZoneInfoNotFoundError:fail('Fuso horário inválido.',422)
    if data.email and not valid_email(data.email):fail('E-mail inválido.',422)
    for k,v in data.model_dump().items():setattr(org,k,v)
    audit(db,org,user,'organization.updated');db.commit()
    return json_response('Configurações salvas.')

# ---------------- RESERVAS E HISTÓRICO ----------------
def _scoped_staff(db,org,staff_id):
    staff=db.scalar(select(Staff).where(Staff.id==staff_id,Staff.organization_id==org.id,Staff.active.is_(True)))
    if not staff:fail('Profissional inválido.',404)
    return staff

def _scoped_service(db,org,service_id):
    service=db.scalar(select(Service).where(Service.id==service_id,Service.organization_id==org.id,Service.active.is_(True)))
    if not service:fail('Serviço inválido.',404)
    return service

def _serialize_booking(org,b):
    return {'id':b.id,'name':b.customer.name,'email':b.customer.email,'service':b.service.name,
            'staff':b.staff.name,'status':b.status,'date':local_dt(org,b.starts_at).date().isoformat(),
            'time':local_dt(org,b.starts_at).strftime('%H:%M'),'price_cents':b.price_cents}

@app.get('/api/public/{slug}/availability')
def public_availability(slug:str,service_id:int,staff_id:int,date:date,db:Session=Depends(get_db)):
    org=get_org(db,slug)
    service=_scoped_service(db,org,service_id)
    staff=_scoped_staff(db,org,staff_id)
    return {'slots':available_slots(db,org,service,staff,date),
            'duration_minutes':service.duration_minutes,'price_cents':service.price_cents}

@app.post('/api/public/{slug}/book',status_code=201)
def book(slug:str,data:NewBookingInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);throttle_shared('book:'+client_ip(request),20,3600);start_write(db)
    org=get_org(db,slug)
    if not db.bind.dialect.name=='sqlite':
        db.scalar(select(PlanSubscription).where(PlanSubscription.organization_id==org.id).with_for_update())
    check_limit(db,org,'bookings')
    email=data.email.strip().lower()
    if not valid_email(email):fail('E-mail inválido.',422)
    if not data.accept_privacy:fail('É necessário aceitar o aviso de privacidade.',422)
    service=_scoped_service(db,org,data.service_id)
    staff=_scoped_staff(db,org,data.staff_id)
    lock_staff(db,org.id,staff.id)
    slots=available_slots(db,org,service,staff,data.date)
    if data.time not in slots:fail('Horário indisponível. Atualize a lista.',409)
    customer=db.scalar(select(Customer).where(Customer.organization_id==org.id,Customer.email==email))
    if not customer:
        customer=Customer(organization_id=org.id,name=text_clean(data.name),email=email,phone=data.phone.strip())
        db.add(customer);db.flush()
    else:
        customer.name=text_clean(data.name)
        if data.phone:customer.phone=data.phone.strip()
    token=new_token()
    when=as_utc_naive(org,data.date,data.time)
    booking=Appointment(organization_id=org.id,customer_id=customer.id,service_id=service.id,staff_id=staff.id,
        starts_at=when,ends_at=when+timedelta(minutes=service.duration_minutes),
        status='pending' if org.require_approval else 'confirmed',notes=data.notes.strip(),
        price_cents=service.price_cents,manage_token_hash=hashed_secret(token),privacy_consent_at=utc_now())
    db.add(booking);db.flush()
    link=f'{config.PUBLIC_BASE_URL}/m/{token}'
    queue_email(db,org,email,f'Agendamento em {org.name}',
        f'Olá, {customer.name}!\n\nSeu agendamento: {service.name}, {data.date.strftime("%d/%m/%Y")} às {data.time}.\n'
        f'Situação: {booking.status}.\nGerencie com este link privado: {link}\n\n{org.name}')
    audit(db,org,None,'booking.created',f'#{booking.id}')
    db.commit()
    return json_response('Reserva registrada.',manage_url=f'/m/{token}',booking_id=booking.id)

@app.get('/api/org/{slug}/bookings')
def list_bookings(slug:str,request:Request,db:Session=Depends(get_db)):
    org,user,member=tenant_guard(request,db,slug)
    items=db.scalars(select(Appointment).where(Appointment.organization_id==org.id).order_by(Appointment.starts_at.desc()).limit(500)).all()
    if member.role=='staff':
        assigned=db.scalar(select(Staff).where(Staff.organization_id==org.id,Staff.user_id==user.id))
        items=[b for b in items if assigned and b.staff_id==assigned.id]
    return {'items':[_serialize_booking(org,b) for b in items]}

@app.patch('/api/org/{slug}/bookings/{booking_id}/status')
def update_booking(slug:str,booking_id:int,data:StatusInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db);org,user,member=tenant_guard(request,db,slug)
    need_active(db,org)
    a=db.scalar(select(Appointment).where(Appointment.organization_id==org.id,Appointment.id==booking_id))
    if not a:fail('Reserva não encontrada.',404)
    if member.role=='staff':
        staff=db.scalar(select(Staff).where(Staff.organization_id==org.id,Staff.user_id==user.id))
        if not staff or a.staff_id!=staff.id:fail('Permissão insuficiente.',403)
    lock_staff(db,org.id,a.staff_id)
    if a.status in ('cancelled','completed') and data.status in ('confirmed','pending'):
        fail('Para reabrir uma reserva concluída ou cancelada, crie uma nova.',409)
    if a.status=='no_show' and data.status=='confirmed':fail('Reserva passada não pode ser reaberta.',409)
    a.status=data.status
    audit(db,org,user,'booking.status',f'{a.id}: {data.status}')
    queue_email(db,org,a.customer.email,'Atualização do agendamento',
                f'Olá, {a.customer.name}. O status do seu agendamento em {org.name} mudou para: {data.status}.')
    db.commit()
    return json_response('Situação atualizada.')

class ManageInput(BaseModel):token:str
class ManageReschedule(BaseModel):
    token:str
    date:date
    time:str=Field(pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')

@app.get('/api/manage/{token}/availability')
def manage_availability(token:str,date:date,db:Session=Depends(get_db)):
    a=db.scalar(select(Appointment).where(Appointment.manage_token_hash==hashed_secret(token)))
    if not a:fail('Reserva não encontrada.',404)
    org=db.get(Organization,a.organization_id)
    return {'slots':available_slots(db,org,a.service,a.staff,date,exclude=a.id)}

@app.post('/api/manage/cancel')
def public_cancel(data:ManageInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);throttle_shared('manage:'+client_ip(request),30,3600);start_write(db)
    a=db.scalar(select(Appointment).where(Appointment.manage_token_hash==hashed_secret(data.token)))
    if not a:fail('Reserva não encontrada.',404)
    org=db.get(Organization,a.organization_id)
    if a.status in ('completed','cancelled','no_show'):fail('Este agendamento não pode ser cancelado.',409)
    if a.starts_at-utc_now()<timedelta(hours=org.cancel_notice_hours):
        fail('Prazo de cancelamento encerrado. Contate o estabelecimento.',409)
    lock_staff(db,org.id,a.staff_id)
    a.status='cancelled'
    audit(db,org,None,'booking.cancelled',str(a.id));db.commit()
    return json_response('Agendamento cancelado.')

@app.post('/api/manage/reschedule')
def public_reschedule(data:ManageReschedule,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);throttle_shared('manage:'+client_ip(request),30,3600);start_write(db)
    a=db.scalar(select(Appointment).where(Appointment.manage_token_hash==hashed_secret(data.token)))
    if not a:fail('Reserva não encontrada.',404)
    org=db.get(Organization,a.organization_id)
    need_active(db,org)
    if a.status not in ('confirmed','pending'):fail('Reserva indisponível para reagendar.',409)
    if a.starts_at-utc_now()<timedelta(hours=org.cancel_notice_hours):fail('Prazo de alteração encerrado.',409)
    lock_staff(db,org.id,a.staff_id)
    if data.time not in available_slots(db,org,a.service,a.staff,data.date,exclude=a.id):
        fail('Horário indisponível.',409)
    a.starts_at=as_utc_naive(org,data.date,data.time)
    a.ends_at=a.starts_at+timedelta(minutes=a.service.duration_minutes)
    audit(db,org,None,'booking.rescheduled',str(a.id))
    queue_email(db,org,a.customer.email,'Novo horário do agendamento',
                f'Olá, {a.customer.name}. Sua nova reserva é {data.date.strftime("%d/%m/%Y")} às {data.time}.')
    db.commit()
    return json_response('Agendamento reagendado.')

@app.get('/api/org/{slug}/export/bookings.csv')
def booking_export(slug:str,request:Request,db:Session=Depends(get_db)):
    org,_,_=tenant_guard(request,db,slug,('owner','manager'))
    out=io.StringIO();w=csv.writer(out)
    w.writerow(['ID','Cliente','E-mail','Telefone','Serviço','Profissional','Data','Hora','Status','Valor (BRL)'])
    for a in db.scalars(select(Appointment).where(Appointment.organization_id==org.id).order_by(Appointment.starts_at.desc())):
        local=local_dt(org,a.starts_at)
        w.writerow([a.id,safe_csv(a.customer.name),safe_csv(a.customer.email),safe_csv(a.customer.phone),
            safe_csv(a.service.name),safe_csv(a.staff.name),local.strftime('%d/%m/%Y'),local.strftime('%H:%M'),
            a.status,f'{a.price_cents/100:.2f}'])
    return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition':f'attachment; filename="agendaflow-{slug}-reservas.csv"','Cache-Control':'no-store'})

@app.get('/api/org/{slug}/export/customers.csv')
def customer_export(slug:str,request:Request,db:Session=Depends(get_db)):
    org,_,_=tenant_guard(request,db,slug,('owner','manager'))
    out=io.StringIO();w=csv.writer(out)
    w.writerow(['Nome','E-mail','Telefone'])
    for c in db.scalars(select(Customer).where(Customer.organization_id==org.id).order_by(Customer.name)):
        w.writerow([safe_csv(c.name),safe_csv(c.email),safe_csv(c.phone)])
    return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="agendaflow-{slug}-clientes.csv"'})

@app.delete('/api/org/{slug}/customers/{customer_id}')
def anonymize_customer(slug:str,customer_id:int,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db);org,user,_=tenant_guard(request,db,slug,('owner',))
    customer=db.scalar(select(Customer).where(Customer.organization_id==org.id,Customer.id==customer_id))
    if not customer:fail('Cliente não encontrado.',404)
    customer.name='Cliente anonimizado'
    customer.email=f'anonymized-{org.id}-{customer.id}@example.invalid'
    customer.phone=''
    for a in db.scalars(select(Appointment).where(Appointment.customer_id==customer.id,Appointment.organization_id==org.id)):
        a.notes=''
    audit(db,org,user,'customer.anonymized',str(customer.id));db.commit()
    return json_response('Dados pessoais anonimizados. Histórico estatístico mantido.')

# ---------------- EQUIPES, PERMISSÕES, COBRANÇA E AUDITORIA ----------------
@app.post('/api/org/{slug}/invite',status_code=201)
def invite_member(slug:str,data:InviteRequest,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);start_write(db)
    org,user,_=tenant_guard(request,db,slug,('owner',))
    need_active(db,org)
    email=data.email.strip().lower()
    if not valid_email(email):fail('E-mail inválido.',422)
    existing_user=db.scalar(select(User).where(User.email==email))
    if existing_user and db.scalar(select(Membership).where(Membership.organization_id==org.id,Membership.user_id==existing_user.id)):
        fail('Este usuário já integra a equipe.',409)
    n=db.scalar(select(func.count(Membership.id)).where(Membership.organization_id==org.id,Membership.active.is_(True))) or 0
    limits=PLAN_LIMITS.get(subscription(db,org.id).plan,PLAN_LIMITS['trial'])
    if n>=limits['staff']+1:fail('Limite de pessoas na equipe atingido.',403)
    token=new_token()
    db.add(Invite(organization_id=org.id,email=email,role=data.role,token_hash=hashed_secret(token),expires_at=utc_now()+timedelta(days=3)))
    queue_email(db,org,email,f'Convite para {org.name} - AgendaFlow',
                f'Você foi convidado(a) para a equipe {org.name}.\nAcesse (válido por 3 dias): {config.PUBLIC_BASE_URL}/invite/{token}')
    audit(db,org,user,'invite.created',f'{data.role} {email}');db.commit()
    return json_response('Convite colocado na fila de e-mail.',status='queued')

@app.get('/api/org/{slug}/audit')
def audit_events(slug:str,request:Request,db:Session=Depends(get_db)):
    org,_,_=tenant_guard(request,db,slug,('owner',))
    events=db.scalars(select(AuditLog).where(AuditLog.organization_id==org.id).order_by(AuditLog.occurred_at.desc()).limit(100)).all()
    return {'items':[{'action':e.action,'details':e.details,'occurred_at':e.occurred_at.isoformat()} for e in events]}

@app.get('/api/org/{slug}/billing')
def billing_status(slug:str,request:Request,db:Session=Depends(get_db)):
    org,_,_=tenant_guard(request,db,slug,('owner',))
    sub=subscription(db,org.id)
    return {'plan':sub.plan,'status':sub.status,'trial_ends_at':sub.trial_ends_at.isoformat(),
            'write_access':is_write_allowed(sub),'limits':PLAN_LIMITS.get(sub.plan,PLAN_LIMITS['trial']),
            'payment_setup':bool(config.STRIPE_SECRET_KEY)}

class CheckoutInput(BaseModel):
    plan:Literal['starter','pro','business']

@app.post('/api/org/{slug}/billing/checkout')
def checkout(slug:str,data:CheckoutInput,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);org,user,_=tenant_guard(request,db,slug,('owner',))
    sub=subscription(db,org.id)
    if not user.email_verified_at and config.PRODUCTION:fail('Confirme seu e-mail antes de contratar um plano.',403)
    if sub.stripe_subscription_id and sub.status in ('active','trialing'):
        fail('Assinatura já vinculada. Gerencie alterações no portal do cliente.',409)
    return {'url':checkout_session(org,sub,user.email,data.plan)}

@app.post('/api/org/{slug}/billing/portal')
def portal(slug:str,request:Request,db:Session=Depends(get_db)):
    require_csrf(request);org,_,_=tenant_guard(request,db,slug,('owner',))
    return {'url':portal_session(org,subscription(db,org.id))}

@app.post('/webhooks/stripe')
async def stripe_webhook(request:Request,db:Session=Depends(get_db)):
    raw=await request.body()
    if len(raw)>1_000_000:fail('Payload muito grande.',413)
    event=verify_signature(raw,request.headers.get('Stripe-Signature',''))
    return process_webhook(db,event)

@app.get('/privacy',response_class=HTMLResponse)
def privacy_page(request:Request,db:Session=Depends(get_db)):
    return template(request,db,'legal.html',kind='privacy')

@app.get('/terms',response_class=HTMLResponse)
def terms_page(request:Request,db:Session=Depends(get_db)):
    return template(request,db,'legal.html',kind='terms')
