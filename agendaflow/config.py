import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env')
ENV = os.getenv('AGENDAFLOW_ENV', 'development')
PRODUCTION = ENV == 'production'
SECRET = os.getenv('AGENDAFLOW_SECRET_KEY', 'development-only-secret-key-please-replace-before-production')
if PRODUCTION and (len(SECRET) < 48 or SECRET.startswith(('development-', 'CHANGE_', 'troque-'))):
    raise RuntimeError('AGENDAFLOW_SECRET_KEY forte e aleatória é obrigatória em produção.')
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./agendaflow_saas.sqlite3')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', 'http://localhost:8000').rstrip('/')
ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PRICE_PRO = os.getenv('STRIPE_PRICE_PRO', '')
STRIPE_PRICE_STARTER = os.getenv("STRIPE_PRICE_STARTER", "")
STRIPE_PRICE_BUSINESS = os.getenv('STRIPE_PRICE_BUSINESS', '')
SMTP_HOST = os.getenv('SMTP_HOST', '')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_FROM = os.getenv('SMTP_FROM', 'AgendaFlow <no-reply@example.invalid>')
SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'suporte@example.invalid')
