"""Capturas de HTML renderizado pelo FastAPI em Chromium, com dados fictícios."""
import re
import base64
from pathlib import Path
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from agendaflow.main import app
ROOT=Path(__file__).resolve().parents[1]
PREV=ROOT/'previews';PREV.mkdir(exist_ok=True)
CSS=(ROOT/'static/styles.css').read_text()
JS=(ROOT/'static/app.js').read_text()
with TestClient(app) as client:
    pages={}
    pages['landing']=client.get('/').text
    pages['reserva']=client.get('/r/studio-aurora').text
    pages['cadastro']=client.get('/signup').text
    login=client.get('/login').text
    match=re.search(r'<meta name="csrf-token" content="([^"]+)"',login)
    assert match
    result=client.post('/api/auth/login',headers={'X-CSRF-Token':match.group(1)},json={
        'email':'marina@demo.agendaflow.local','password':'DemoSeguro#2026'})
    assert result.status_code==200,result.text
    for slug,url in [
        ('painel','/app/studio-aurora'),('servicos','/app/studio-aurora/services'),
        ('agenda','/app/studio-aurora/appointments'),('equipe','/app/studio-aurora/team'),
        ('assinatura','/app/studio-aurora/billing'),('clientes','/app/studio-aurora/customers'),
        ('configuracoes','/app/studio-aurora/settings')]:
        r=client.get(url)
        assert r.status_code==200,(url,r.status_code,r.text[:200])
        pages[slug]=r.text
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox','--disable-dev-shm-usage'])
    def shot(name,key,theme='light',width=1440,height=920,full_page=False):
        raw=pages[key]
        # Inline local SVG for offline capture: browser preview cannot use localhost assets.
        mascot=(ROOT/'static/clock-mascot.svg').read_bytes()
        raw=raw.replace('src="/static/clock-mascot.svg"','src="data:image/svg+xml;base64,'+base64.b64encode(mascot).decode()+'"')
        raw=re.sub(r'<link\b[^>]+>','',raw)
        raw=re.sub(r'<script defer src="[^"]+"></script>','',raw)
        raw=raw.replace('</head>',f'<style>{CSS}</style><style>.reveal{{opacity:1!important;transform:none!important}}</style></head>')
        # preserve main JS via direct injection for UI behavior and JS error validation
        page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
        errors=[];page.on('pageerror',lambda exc:errors.append(str(exc)))
        page.set_content(raw,wait_until='domcontentloaded')
        page.add_script_tag(content=JS)
        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
        page.wait_for_timeout(200)
        page.screenshot(path=str(PREV/(name+'.png')),full_page=full_page,animations='disabled')
        overflow=page.evaluate('document.documentElement.scrollWidth>window.innerWidth')
        print(f'{name}: theme={theme}, horizontal_overflow={overflow}, js_errors={errors}')
        page.close()
    shot('landing-claro','landing',full_page=True)
    shot('landing-escuro','landing',theme='dark',full_page=True)
    shot('painel-claro','painel')
    shot('painel-escuro','painel',theme='dark')
    shot('agenda-claro','agenda')
    shot('servicos-claro','servicos')
    shot('equipe-escuro','equipe',theme='dark')
    shot('assinatura-claro','assinatura')
    shot('reservar-claro','reserva',full_page=True)
    shot('landing-mobile','landing',width=390,height=844)
    shot('reserva-mobile','reserva',width=390,height=844)
    shot('painel-mobile','painel',width=390,height=844)
    browser.close()
