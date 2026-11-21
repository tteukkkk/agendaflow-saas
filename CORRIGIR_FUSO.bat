@echo off
setlocal
cd /d "%~dp0"
title AgendaFlow - Corrigir fuso horario
cls
echo.
echo  AGENDAFLOW - Corrigir fuso horario do Windows
echo.
if not exist "\.venv\Scripts\python.exe" (
    echo [INFO] Ambiente ainda nao instalado.
    echo Execute ABRIR_AGENDAFLOW.bat para preparar o AgendaFlow.
    goto :fim
)
echo Instalando tzdata no ambiente virtual do AgendaFlow...
"\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check tzdata
if errorlevel 1 (
    echo [ERRO] Falha ao instalar o banco de fusos. Confira a internet.
    goto :fim
)
"\.venv\Scripts\python.exe" -c "from zoneinfo import ZoneInfo; print('Fuso validado:',ZoneInfo('America/Sao_Paulo'))"
if errorlevel 1 (
    echo [ERRO] Ainda nao foi possivel carregar America/Sao_Paulo.
) else (
    echo [OK] Fuso corrigido. Execute ABRIR_AGENDAFLOW.bat.
)
:fim
echo.
pause
endlocal
