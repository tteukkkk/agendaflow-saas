import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from argon2 import PasswordHasher, exceptions
from fastapi import HTTPException, Request
from sqlalchemy import select
from .models import User, Membership, Organization

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_attempts = defaultdict(deque)  # somente fallback local; em produção usar rate limiter no gateway

def hashed_secret(token:str)->str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def new_token()->str:
    return secrets.token_urlsafe(40)

def password_hash(raw:str)->str:
    return _hasher.hash(raw)

def check_password(raw:str, encoded:str)->bool:
    try:
        return _hasher.verify(encoded,raw)
    except (exceptions.VerifyMismatchError,exceptions.VerificationError,exceptions.InvalidHashError):
        return False

def valid_email(s:str)->bool:
    return bool(re.fullmatch(r'[^\s@]{1,100}@[^\s@]{1,100}\.[^\s@]{2,}',s)) and len(s)<=200

def require_csrf(request:Request):
    expected=request.session.get('csrf')
    supplied=request.headers.get('X-CSRF-Token')
    origin=request.headers.get('origin')
    if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
        raise HTTPException(403,'Origem não permitida.')
    if not expected or not supplied or not hmac.compare_digest(expected,supplied):
        raise HTTPException(403,'Token de segurança inválido.')

def csrf_token(request:Request)->str:
    if not request.session.get('csrf'):
        request.session['csrf']=secrets.token_urlsafe(32)
    return request.session['csrf']

def user_for(request:Request,db):
    uid=request.session.get('uid')
    if not isinstance(uid,int):return None
    u=db.get(User,uid)
    return u if u and u.active and request.session.get('sv')==u.session_version else None

def require_user(request:Request,db)->User:
    u=user_for(request,db)
    if not u:raise HTTPException(401,'Faça login para continuar.')
    return u

def member_for(db,user,org):
    if not user:return None
    return db.scalar(select(Membership).where(Membership.organization_id==org.id,Membership.user_id==user.id,Membership.active.is_(True)))

def tenant_guard(request:Request,db,slug:str,roles=('owner','manager','staff')):
    user=require_user(request,db)
    org=db.scalar(select(Organization).where(Organization.slug==slug))
    if not org:raise HTTPException(404,'Empresa não encontrada.')
    member=member_for(db,user,org)
    if not member or member.role not in roles:
        # Não revelar existência do workspace para estranhos
        raise HTTPException(404,'Workspace indisponível.')
    return org,user,member

def throttle(key:str,limit=12,seconds=300):
    now=time.monotonic()
    queue=_attempts[key]
    while queue and now-queue[0]>seconds:queue.popleft()
    if len(queue)>=limit:raise HTTPException(429,'Muitas solicitações. Tente mais tarde.')
    queue.append(now)

def client_ip(request:Request)->str:
    # Nunca confiar em X-Forwarded-For fornecido pelo cliente.
    return request.client.host if request.client else 'unknown'


def throttle_shared(key:str,limit:int=12,seconds:int=300):
    """Limitador centralizado no banco para instâncias múltiplas; limpeza em job de manutenção."""
    from sqlalchemy import text
    from .db import SessionLocal,IS_SQLITE
    from .models import RateLimitBucket,utc_now
    from datetime import timedelta
    digest=hashlib.sha256(key.encode()).hexdigest()
    with SessionLocal() as db:
        if IS_SQLITE:
            db.execute(text('BEGIN IMMEDIATE'))
        else:
            lock_key=int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'big',signed=True)
            db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':lock_key})
        row=db.get(RateLimitBucket,digest)
        now=utc_now()
        if not row:
            row=RateLimitBucket(key_hash=digest,window_started_at=now,count=1);db.add(row)
        elif row.window_started_at+timedelta(seconds=seconds)<=now:
            row.window_started_at=now;row.count=1
        else:
            row.count+=1
        denied=row.count>limit
        db.commit()
    if denied:raise HTTPException(429,'Limite de tentativas atingido. Tente novamente mais tarde.')
