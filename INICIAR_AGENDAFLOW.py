#!/usr/bin/env python3
"""Inicia apenas o AgendaFlow, isolado e sem tocar no banco principal.

Abrir pelo arquivo ABRIR_AGENDAFLOW.bat em Windows.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT
USER = 'marina@demo.agendaflow.local'
PASSWORD = 'DemoSeguro#2026'
PORTS = range(8030, 8040)


def run(*cmd: str, env: dict[str, str] | None = None) -> None:
    subprocess.run([str(part) for part in cmd], check=True, cwd=APP, env=env)


def python_env() -> Path:
    if sys.version_info < (3, 12):
        raise RuntimeError(f'Python 3.12+ necessario; encontrado {sys.version_info.major}.{sys.version_info.minor}.')
    folder = APP / '.venv'
    executable = folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not executable.exists():
        print('[1/4] Criando ambiente Python isolado...', flush=True)
        venv.EnvBuilder(with_pip=True).create(str(folder))
    requirements = (APP / 'requirements.txt').read_text(encoding='utf-8')
    marker = folder / 'requirements-ok.txt'
    if not marker.exists() or marker.read_text(encoding='utf-8') != requirements:
        print('[2/4] Instalando dependencias (na primeira vez precisa de internet)...', flush=True)
        run(str(executable), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements.txt')
        marker.write_text(requirements, encoding='utf-8')
    else:
        print('[2/4] Dependencias ja preparadas.', flush=True)
    ensure_timezone_data(executable)
    return executable


def ensure_timezone_data(executable: Path) -> None:
    """Evita falha do zoneinfo no Windows (que nao traz a base IANA).

    A verificacao tambem corrige um .venv antigo com dependencias incompletas.
    """
    probe = 'from zoneinfo import ZoneInfo; ZoneInfo("America/Sao_Paulo")'
    check = lambda: subprocess.run(
        [str(executable), '-c', probe], cwd=APP,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors='replace', check=False
    )
    if check().returncode == 0:
        print('    Fuso horario de Sao Paulo verificado.', flush=True)
        return
    print('    Base de fusos nao encontrada. Instalando tzdata...', flush=True)
    run(str(executable), '-m', 'pip', 'install', '--disable-pip-version-check', 'tzdata>=2024.1')
    if check().returncode != 0:
        raise RuntimeError('Nao foi possivel instalar os fusos horarios. Confira a conexao de internet e execute: ./.venv/Scripts/python.exe -m pip install tzdata')
    print('    Fusos horarios preparados com sucesso.', flush=True)


def choose_port() -> int:
    for port in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError('Portas 8030 a 8039 ocupadas. Feche outros servidores AgendaFlow.')


def environment(name: str, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env['AGENDAFLOW_ENV'] = 'development'
    env['DATABASE_URL'] = f'sqlite:///./{name}'
    env['PUBLIC_BASE_URL'] = f'http://127.0.0.1:{port}'
    path = APP / '.venv' / 'demo-secret.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_urlsafe(64), encoding='utf-8')
    env['AGENDAFLOW_SECRET_KEY'] = path.read_text(encoding='utf-8').strip()
    return env


def verify_account(py: Path, env: dict[str, str]) -> bool:
    # Executa a verificacao no proprio ORM, com o mesmo banco e senha do servidor.
    check = (
        'from sqlalchemy import select; '
        'from agendaflow.db import SessionLocal; '
        'from agendaflow.models import User,Organization,Membership; '
        'from agendaflow.security import check_password; '
        'db=SessionLocal(); '
        'u=db.scalar(select(User).where(User.email=="marina@demo.agendaflow.local")); '
        'o=db.scalar(select(Organization).where(Organization.slug=="studio-aurora")); '
        'm=(db.scalar(select(Membership).where(Membership.user_id==u.id,Membership.organization_id==o.id,Membership.active.is_(True))) if u is not None and o is not None else None); '
        'assert u is not None and u.active and m is not None and check_password("DemoSeguro#2026",u.password_hash),"Conta demo invalida"; '
        'print("Login de demonstracao validado")'
    )
    result = subprocess.run([str(py), '-c', check], env=env, cwd=APP,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace')
    if result.returncode != 0:
        print('A conta de demonstracao nao esta valida neste banco.', flush=True)
    return result.returncode == 0


def demo_db(py: Path, port: int) -> tuple[str, dict[str, str]]:
    # Nunca altera banco padrao ou um banco demo com credenciais diferentes.
    for i in range(1, 21):
        name = f'agendaflow_capturas_{i}.sqlite3'
        path = APP / name
        env = environment(name, port)
        if path.exists():
            if verify_account(py, env):
                print('[3/4] Banco de demonstracao existente e valido:', name, flush=True)
                return name, env
            print('Preservando banco anterior com conta diferente:', name, flush=True)
            continue
        print('[3/4] Criando dados ficticios de agendamentos...', flush=True)
        run(str(py), '-m', 'scripts.dev_init', env=env)
        run(str(py), '-m', 'scripts.seed_demo', env=env)
        if not verify_account(py, env):
            raise RuntimeError('O banco novo foi criado, mas a senha demonstrativa nao foi validada.')
        return name, env
    raise RuntimeError('Limite de bancos de demonstracao atingido; preserve seus arquivos antes de limpar.')


def wait_started(port: int, server: subprocess.Popen) -> None:
    url = f'http://127.0.0.1:{port}/health'
    for _ in range(75):
        if server.poll() is not None:
            raise RuntimeError('O processo web encerrou; veja a mensagem acima.')
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                data = json.load(response)
                if data.get('status') == 'ok' and data.get('version') == '2.0.0':
                    return
        except Exception:
            pass
        time.sleep(0.35)
    raise RuntimeError('O servidor nao respondeu ao health check. Confira mensagens acima.')


def main() -> None:
    if not (APP / 'agendaflow' / 'main.py').exists():
        raise RuntimeError('Projeto incompleto. Extraia TODO o arquivo ZIP antes de executar.')
    print('AgendaFlow — execucao independente para escolher prints', flush=True)
    py = python_env()
    port = choose_port()
    db_name, env = demo_db(py, port)
    cmd = [str(py), '-m', 'uvicorn', 'agendaflow.main:app', '--host', '127.0.0.1', '--port', str(port), '--no-access-log']
    print('[4/4] Iniciando site, mantendo esta janela aberta...', flush=True)
    server = subprocess.Popen(cmd, cwd=APP, env=env)
    try:
        wait_started(port, server)
        url = f'http://127.0.0.1:{port}/login'
        print('\n' + '=' * 64, flush=True)
        print('  AGENDAFLOW PRONTO — ABRINDO NAVEGADOR', flush=True)
        print('  Endereco: ', url, flush=True)
        print('  Usuario:  ', USER, flush=True)
        print('  Senha:    ', PASSWORD, flush=True)
        print('  Banco demo:', db_name, '(separado do seu banco anterior)', flush=True)
        print('  Booking:  ', f'http://127.0.0.1:{port}/r/studio-aurora', flush=True)
        print('  Para encerrar: pressione CTRL+C nesta janela.', flush=True)
        print('=' * 64 + '\n', flush=True)
        webbrowser.open(url, new=2)
        server.wait()
    finally:
        if server.poll() is None:
            server.terminate()
            try: server.wait(timeout=4)
            except subprocess.TimeoutExpired: server.kill()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nAgendaFlow encerrado.', flush=True)
    except (subprocess.CalledProcessError, RuntimeError, OSError) as error:
        print('\n[ERRO] ', error, file=sys.stderr, flush=True)
        sys.exit(1)
