"""Regressoes: Windows precisa de tzdata quando nao ha base IANA do sistema."""
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo, reset_tzpath


def _launcher():
    filename = Path(__file__).resolve().parents[1] / 'INICIAR_AGENDAFLOW.py'
    spec = importlib.util.spec_from_file_location('agendaflow_windows_launcher', filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_timezone_in_python_without_os_timezone_files():
    """PYTHONTZPATH vazio emula a falta da base IANA no Windows."""
    script = 'from zoneinfo import ZoneInfo; assert ZoneInfo("America/Sao_Paulo").key == "America/Sao_Paulo"'
    result = subprocess.run([sys.executable, '-c', script], env={**__import__('os').environ, 'PYTHONTZPATH': ''}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_launcher_installs_tzdata_if_timezone_is_missing(monkeypatch):
    module = _launcher()
    probes = iter([1, 0])
    install = []
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=next(probes)))
    monkeypatch.setattr(module, 'run', lambda *args: install.append(args))
    module.ensure_timezone_data(Path('python.exe'))
    assert len(install) == 1
    assert 'tzdata>=2024.1' in install[0]


def test_launcher_does_not_reinstall_if_timezone_exists(monkeypatch):
    module = _launcher()
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(module, 'run', lambda *args: (_ for _ in ()).throw(AssertionError('Unexpected install')))
    module.ensure_timezone_data(Path('python.exe'))


def test_booking_unknown_timezone_uses_saopaulo_fallback():
    from agendaflow.booking import zone
    assert zone(SimpleNamespace(timezone='Invalid/Region')).key == 'America/Sao_Paulo'
