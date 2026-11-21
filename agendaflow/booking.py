"""Horários UTC, apresentação em timezone da empresa e serialização concorrente por profissional."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException
from sqlalchemy import select, text
from .db import IS_SQLITE
from .models import Appointment, Staff, Service, WorkHours, TimeOff, utc_now
ACTIVE=('confirmed','pending')

def zone(org):
    try:
        return ZoneInfo(org.timezone)
    except ZoneInfoNotFoundError:
        try:
            return ZoneInfo('America/Sao_Paulo')
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(
                'Base de fusos IANA ausente. Instale no ambiente Python: python -m pip install tzdata'
            ) from exc

def local_dt(org,utc_value):
    return utc_value.replace(tzinfo=timezone.utc).astimezone(zone(org))

def as_utc_naive(org,day:date,clock:str):
    try: hour=time.fromisoformat(clock)
    except ValueError:raise HTTPException(422,'Horário inválido.')
    return datetime.combine(day,hour,tzinfo=zone(org)).astimezone(timezone.utc).replace(tzinfo=None)

def org_day(org,dt=None):
    return local_dt(org,dt or utc_now()).date()

def lock_staff(db,org_id:int,staff_id:int):
    if IS_SQLITE:
        start_write(db)
    else:
        # Evita leituras concorrentes entre disponibilidade e gravação em PostgreSQL
        key=((org_id & 0x7fffffff)<<32) | (staff_id & 0xffffffff)
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':key})

def available_slots(db,org,service:Service,staff:Staff,day:date,exclude:int|None=None):
    today=org_day(org)
    if service.organization_id!=org.id or staff.organization_id!=org.id or not service.active or not staff.active:
        return []
    if day<today or day>today+timedelta(days=org.booking_window_days):return []
    hours=db.scalar(select(WorkHours).where(WorkHours.staff_id==staff.id,WorkHours.weekday==day.weekday()))
    if not hours or hours.closed:return []
    try:
        open_min=time.fromisoformat(hours.opens_at).hour*60+time.fromisoformat(hours.opens_at).minute
        close_min=time.fromisoformat(hours.closes_at).hour*60+time.fromisoformat(hours.closes_at).minute
        break_start=time.fromisoformat(hours.break_start).hour*60+time.fromisoformat(hours.break_start).minute if hours.break_start else None
        break_end=time.fromisoformat(hours.break_end).hour*60+time.fromisoformat(hours.break_end).minute if hours.break_end else None
    except ValueError:return []
    if close_min<=open_min or org.slot_step not in (15,30,60):return []
    begin=as_utc_naive(org,day,'00:00')
    end=as_utc_naive(org,day+timedelta(days=1),'00:00')
    appts=db.scalars(select(Appointment).where(Appointment.organization_id==org.id,Appointment.staff_id==staff.id,Appointment.status.in_(ACTIVE),Appointment.starts_at<end,Appointment.ends_at>begin)).all()
    if exclude:appts=[a for a in appts if a.id!=exclude]
    blocks=db.scalars(select(TimeOff).where(TimeOff.organization_id==org.id,TimeOff.staff_id==staff.id,TimeOff.starts_at<end,TimeOff.ends_at>begin)).all()
    earliest=utc_now()+timedelta(hours=org.min_notice_hours)
    slots=[]
    for m in range(open_min,close_min-service.duration_minutes+1,org.slot_step):
        finish_local=m+service.duration_minutes
        if break_start is not None and break_end is not None and m<break_end and finish_local>break_start:continue
        clock=f'{m//60:02d}:{m%60:02d}'
        start=as_utc_naive(org,day,clock)
        finish=start+timedelta(minutes=service.duration_minutes)
        if start<earliest or any(start<a.ends_at and finish>a.starts_at for a in appts):continue
        if any(start<b.ends_at and finish>b.starts_at for b in blocks):continue
        slots.append(clock)
    return slots


def start_write(db):
    if IS_SQLITE and not db.info.get('write_locked'):
        db.execute(text('BEGIN IMMEDIATE'))
        db.info['write_locked']=True
