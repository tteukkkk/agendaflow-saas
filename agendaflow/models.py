from datetime import datetime, timedelta, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    email_verified_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    terms_accepted_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(75), unique=True, index=True)
    tagline: Mapped[str] = mapped_column(String(180), default='Seu tempo, bem cuidado.')
    email: Mapped[str] = mapped_column(String(200), default='')
    phone: Mapped[str] = mapped_column(String(40), default='')
    timezone: Mapped[str] = mapped_column(String(60), default='America/Sao_Paulo')
    address: Mapped[str] = mapped_column(String(220), default='')
    booking_window_days: Mapped[int] = mapped_column(Integer, default=60)
    slot_step: Mapped[int] = mapped_column(Integer, default=30)
    min_notice_hours: Mapped[int] = mapped_column(Integer, default=2)
    cancel_notice_hours: Mapped[int] = mapped_column(Integer, default=4)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_notice: Mapped[str] = mapped_column(Text, default='Seus dados de contato serão utilizados para administrar seu agendamento e enviar comunicações relacionadas a ele.')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

class Membership(Base):
    __tablename__ = 'memberships'
    __table_args__ = (UniqueConstraint('organization_id','user_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    role: Mapped[str] = mapped_column(String(20), default='staff')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped[User] = relationship()

class PlanSubscription(Base):
    __tablename__ = 'subscriptions'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), unique=True)
    plan: Mapped[str] = mapped_column(String(20), default='trial')
    status: Mapped[str] = mapped_column(String(24), default='trialing')
    trial_ends_at: Mapped[datetime] = mapped_column(DateTime, default=lambda:utc_now()+timedelta(days=14))
    stripe_customer_id: Mapped[str|None] = mapped_column(String(110), unique=True, nullable=True)
    stripe_subscription_id: Mapped[str|None] = mapped_column(String(110), unique=True, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    last_stripe_event_created: Mapped[int] = mapped_column(Integer, default=0)

class Service(Base):
    __tablename__='services'
    __table_args__=(UniqueConstraint('organization_id','id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default='')
    category: Mapped[str] = mapped_column(String(60), default='Geral')
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[str] = mapped_column(String(20), default='#7c5cff')
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Staff(Base):
    __tablename__='staff'
    __table_args__=(UniqueConstraint('organization_id','id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int|None] = mapped_column(ForeignKey('users.id'), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), default='')
    specialty: Mapped[str] = mapped_column(String(130), default='Profissional')
    color: Mapped[str] = mapped_column(String(20), default='#8b5cf6')
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class WorkHours(Base):
    __tablename__='work_hours'
    __table_args__=(UniqueConstraint('staff_id','weekday'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey('staff.id', ondelete='CASCADE'), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    opens_at: Mapped[str] = mapped_column(String(5), default='09:00')
    closes_at: Mapped[str] = mapped_column(String(5), default='18:00')
    break_start: Mapped[str] = mapped_column(String(5), default='12:00')
    break_end: Mapped[str] = mapped_column(String(5), default='13:00')
    closed: Mapped[bool] = mapped_column(Boolean, default=False)

class TimeOff(Base):
    __tablename__='time_off'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey('staff.id', ondelete='CASCADE'), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(String(180), default='Bloqueio')

class Customer(Base):
    __tablename__='customers'
    __table_args__=(UniqueConstraint('organization_id','email'),UniqueConstraint('organization_id','id'))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(40), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

class Appointment(Base):
    __tablename__='appointments'
    __table_args__=(Index('ix_appt_org_start','organization_id','starts_at'),
        ForeignKeyConstraint(['organization_id','customer_id'],['customers.organization_id','customers.id']),
        ForeignKeyConstraint(['organization_id','staff_id'],['staff.organization_id','staff.id']),
        ForeignKeyConstraint(['organization_id','service_id'],['services.organization_id','services.id']))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    staff_id: Mapped[int] = mapped_column(Integer, index=True)
    service_id: Mapped[int] = mapped_column(Integer, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC sem tzinfo
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(24), default='confirmed')
    notes: Mapped[str] = mapped_column(Text, default='')
    manage_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    privacy_consent_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    customer: Mapped[Customer] = relationship(viewonly=True)
    staff: Mapped[Staff] = relationship(viewonly=True)
    service: Mapped[Service] = relationship(viewonly=True)

class EmailOutbox(Base):
    __tablename__='email_outbox'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    to_email: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(250))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default='queued')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    sent_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)

class AuditLog(Base):
    __tablename__='audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    actor_user_id: Mapped[int|None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[str] = mapped_column(String(260), default='')
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

class WebhookEvent(Base):
    __tablename__='webhook_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_event_id: Mapped[str] = mapped_column(String(180), unique=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

class EmailVerification(Base):
    __tablename__='email_verifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'))
    token_hash: Mapped[str] = mapped_column(String(64),unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)

class ResetToken(Base):
    __tablename__='reset_tokens'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)

class Invite(Base):
    __tablename__='invites'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'))
    email: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default='staff')
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)


class RateLimitBucket(Base):
    __tablename__='rate_limit_buckets'
    key_hash: Mapped[str] = mapped_column(String(64),primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime,default=utc_now)
    count: Mapped[int] = mapped_column(Integer,default=0)
