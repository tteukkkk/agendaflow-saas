"""Stripe Billing (não armazena informações de cartão). Requer chaves e produtos reais."""
import hashlib
import hmac
import json
import time
import httpx
from fastapi import HTTPException
from sqlalchemy import select
from . import config
from .models import PlanSubscription, Organization, WebhookEvent
from datetime import datetime, timezone

PRICE_BY_PLAN={
  'starter':config.STRIPE_PRICE_STARTER,
  'pro':config.STRIPE_PRICE_PRO,
  'business':config.STRIPE_PRICE_BUSINESS,
}

def stripe_post(path:str,data:dict):
    if not config.STRIPE_SECRET_KEY:raise HTTPException(503,'Cobrança indisponível: Stripe ainda não foi configurado.')
    try:
        response=httpx.post('https://api.stripe.com/v1/'+path,auth=(config.STRIPE_SECRET_KEY,''),data=data,timeout=20)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502,'O provedor de pagamento recusou a solicitação.') from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503,'Não foi possível contatar o provedor de pagamento.') from exc

def checkout_session(org,sub,owner_email,plan):
    price=PRICE_BY_PLAN.get(plan)
    if not price:raise HTTPException(503,'Plano de pagamento ainda não configurado.')
    data={
        'mode':'subscription',
        'line_items[0][price]':price,'line_items[0][quantity]':'1',
        'client_reference_id':str(org.id),
        'success_url':f'{config.PUBLIC_BASE_URL}/app/{org.slug}/billing?return=success',
        'cancel_url':f'{config.PUBLIC_BASE_URL}/app/{org.slug}/billing?return=cancel',
        'subscription_data[metadata][organization_id]':str(org.id),
        'subscription_data[metadata][selected_plan]':plan,
        'metadata[organization_id]':str(org.id),
        'metadata[selected_plan]':plan,
        'allow_promotion_codes':'true',
    }
    if sub.stripe_customer_id:data['customer']=sub.stripe_customer_id
    else:data['customer_email']=owner_email
    result=stripe_post('checkout/sessions',data)
    if not result.get('url','').startswith('https://checkout.stripe.com/'):
        raise HTTPException(502,'Resposta de checkout inválida.')
    return result['url']

def portal_session(org,sub):
    if not sub.stripe_customer_id:raise HTTPException(400,'Nenhuma assinatura vinculada a esta empresa.')
    result=stripe_post('billing_portal/sessions',{
        'customer':sub.stripe_customer_id,
        'return_url':f'{config.PUBLIC_BASE_URL}/app/{org.slug}/billing',
    })
    if not result.get('url','').startswith('https://billing.stripe.com/'):
        raise HTTPException(502,'Portal de cobrança indisponível.')
    return result['url']

def verify_signature(payload:bytes,signature_header:str):
    if not config.STRIPE_WEBHOOK_SECRET:raise HTTPException(503,'Webhook ainda não configurado.')
    parts={}
    for entry in signature_header.split(','):
        k,sep,v=entry.partition('=')
        if sep:parts.setdefault(k,[]).append(v)
    try:stamp=int(parts.get('t',['0'])[0])
    except ValueError:raise HTTPException(400,'Assinatura inválida.')
    if abs(time.time()-stamp)>300:raise HTTPException(400,'Assinatura expirada.')
    body=(str(stamp)+'.').encode()+payload
    actual=hmac.new(config.STRIPE_WEBHOOK_SECRET.encode(),body,hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(actual,s) for s in parts.get('v1',[])):
        raise HTTPException(400,'Assinatura inválida.')
    try:return json.loads(payload)
    except ValueError:raise HTTPException(400,'Evento malformado.')

def _match_plan(subscription_obj):
    items=(subscription_obj.get('items') or {}).get('data') or []
    prices={i.get('price',{}).get('id') for i in items}
    for name,pid in PRICE_BY_PLAN.items():
        if pid and pid in prices:return name
    return None

def _process_subscription(db,obj,event_created=0):
    customer=obj.get('customer')
    remote_id=obj.get('id')
    if not customer or not remote_id:return
    sub=db.scalar(select(PlanSubscription).where(PlanSubscription.stripe_subscription_id==remote_id))
    if not sub:
        sub=db.scalar(select(PlanSubscription).where(PlanSubscription.stripe_customer_id==customer))
    if not sub:
        # Aceita o relacionamento somente se metadata autenticada e org sem customer conflitante.
        meta=obj.get('metadata') or {}
        try:oid=int(meta.get('organization_id','0'))
        except (ValueError,TypeError):return
        sub=db.scalar(select(PlanSubscription).where(PlanSubscription.organization_id==oid))
        if not sub or (sub.stripe_customer_id and sub.stripe_customer_id!=customer):return
    if sub.stripe_customer_id and sub.stripe_customer_id!=customer:return
    if event_created and event_created<sub.last_stripe_event_created:return
    if sub.stripe_subscription_id and sub.stripe_subscription_id!=remote_id:
        # Permite nova assinatura somente após cancelamento/encerramento da anterior.
        # A metadata precisa vir do objeto assinado pela Stripe para evitar vínculo cruzado.
        meta=obj.get('metadata') or {}
        try: metadata_org=int(meta.get('organization_id','0'))
        except (ValueError,TypeError):return
        if sub.status not in ('cancelled','unpaid','incomplete_expired') or metadata_org!=sub.organization_id:return
    plan=_match_plan(obj)
    if not plan:return  # Nunca aceitar preço desconhecido ou upgrade pela metadata.
    status=obj.get('status','')
    if status not in {'active','trialing','past_due','canceled','unpaid','incomplete','incomplete_expired','paused'}:return
    sub.stripe_customer_id=customer
    sub.stripe_subscription_id=remote_id
    sub.plan=plan
    sub.last_stripe_event_created=event_created or sub.last_stripe_event_created
    sub.status='cancelled' if status=='canceled' else status
    if status=='trialing' and obj.get('trial_end'):
        try:sub.trial_ends_at=datetime.fromtimestamp(int(obj['trial_end']),tz=timezone.utc).replace(tzinfo=None)
        except (TypeError,ValueError,OverflowError):pass

def process_webhook(db,event):
    evt_id=event.get('id','')
    if not evt_id or len(evt_id)>180:raise HTTPException(400,'Evento inválido.')
    if db.scalar(select(WebhookEvent).where(WebhookEvent.provider_event_id==evt_id)):
        return {'received':True,'duplicate':True}
    kind=event.get('type','')
    obj=(event.get('data') or {}).get('object') or {}
    if kind=='checkout.session.completed' and obj.get('mode')=='subscription':
        # Apenas registra o cliente. Direitos são atualizados pelo evento subscription.*, com preço validado.
        try:oid=int(obj.get('client_reference_id','0'))
        except (ValueError,TypeError):oid=0
        sub=db.scalar(select(PlanSubscription).where(PlanSubscription.organization_id==oid))
        customer=obj.get('customer')
        if sub and customer and (not sub.stripe_customer_id or sub.stripe_customer_id==customer):
            sub.stripe_customer_id=customer
    elif kind in ('customer.subscription.created','customer.subscription.updated','customer.subscription.deleted'):
        _process_subscription(db,obj,event.get('created',0))
    db.add(WebhookEvent(provider='stripe',provider_event_id=evt_id))
    db.commit()
    return {'received':True}
